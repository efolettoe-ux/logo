"""Comando estampar: mapa.csv + mockups lisos + estampas -> imagens finais padronizadas.

Planejamento (o que gerar) é separado da execução (pixels), para rodar em paralelo e para os testes.
"""
from __future__ import annotations

import csv
import os
import statistics
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image

from catalogo import (ErroUsuario, LinhaMapa, Produto, Projeto, cor_por_nome, ler_catalogo, ler_mapa,
                      nome_arquivo_saida, numeracao_lados, sem_acentos, texto_descricao)
from mockups import ResultadoMockups, registro_em_cache

COLUNAS_RELATORIO = ["handle", "NOME", "cor", "codigo", "vista", "numero", "arquivo", "status", "estampa",
                     "origem_geometria", "largura_rel", "topo_rel", "centro_x_rel", "segundos", "observacao"]

NOME_VISTA_SAIDA = {"costas": "costas", "frente": "frente", "close-costas": "close"}


@dataclass
class Vista:
    vista: str                       # costas | frente | close-costas
    numero: int
    mockup: Optional[str]            # caminho do mockup liso (None = sem_mockup)
    mockup_costas: Optional[str]     # para o close: mockup das costas (registro)
    estampa: Optional[str]           # caminho da arte (None = lado liso)
    geometria: Optional[Tuple[float, float, float]]
    origem_geometria: str = ""
    arquivo_png: str = ""
    arquivo_web: str = ""
    arquivo_transparente: str = ""
    status: str = ""                 # preenchido no planejamento (sem_mockup/pulado) ou na execução
    observacao: str = ""


@dataclass
class Tarefa:
    handle: str
    nome: str
    cor: str
    codigo: str
    vistas: List[Vista] = field(default_factory=list)
    status: str = ""                 # sem_estampa | sem_mockup | liso -> nada a gerar
    observacao: str = ""


# ---------------------------------------------------------------------------
# Planejamento
# ---------------------------------------------------------------------------

def _resolver_estampa(proj: Projeto, linha: LinhaMapa) -> Optional[Path]:
    """id_normalizado (estampas_normalizadas/{id}.png, gerado pelo casar) ou arquivo_estampa."""
    if linha.id_normalizado and not linha.eh_liso:
        p = proj.pasta("estampas_normalizadas") / (linha.id_normalizado
                                                    if linha.id_normalizado.lower().endswith(".png")
                                                    else linha.id_normalizado + ".png")
        if p.exists():
            return p
    if linha.arquivo_estampa and not linha.eh_liso:
        p = Path(linha.arquivo_estampa).expanduser()
        if not p.is_absolute():
            bases = [proj.raiz, proj.pasta("estampas")]
            try:
                from casamento import achar_raiz_arquivos
                r = achar_raiz_arquivos(proj)
                if r is not None:
                    bases.insert(0, r)
            except Exception:  # noqa: BLE001
                pass
            for base in bases:
                if (base / p).exists():
                    return base / p
            return bases[0] / p
        return p
    return None


def _linhas_do(handle: str, cor: str, lado: str, mapa: Dict[str, List[LinhaMapa]]) -> Optional[LinhaMapa]:
    """Linha específica da cor; se não houver, a linha 'todas as cores' (cor vazia)."""
    cands = [l for l in mapa.get(handle, []) if l.lado == lado]
    for l in cands:
        if l.cor == cor:
            return l
    for l in cands:
        if not l.cor:
            return l
    return None


def geometria_do_produto(linhas: List[LinhaMapa], lado: str) -> Optional[Tuple[float, float, float]]:
    """Mediana entre as cores do mesmo produto e lado (as fotos atuais variam ~1-2% de cor para cor)."""
    gs = [l.geometria() for l in linhas if l.lado == lado and not l.eh_liso]
    gs = [g for g in gs if g is not None]
    if not gs:
        return None
    return tuple(round(statistics.median(v), 4) for v in zip(*gs))


def geometrias_da_analise(linhas: List[dict]) -> Dict[Tuple[str, str], Tuple[float, float, float]]:
    """(handle, lado) -> mediana da geometria medida nas fotos atuais (todas as cores)."""
    grupos: Dict[Tuple[str, str], List[Tuple[float, float, float]]] = {}
    for l in linhas:
        try:
            g = (float(l["largura_rel"]), float(l["topo_rel"]), float(l.get("centro_x_rel") or 0))
        except (KeyError, TypeError, ValueError):
            continue
        if l.get("handle") and l.get("lado") in ("frente", "costas"):
            grupos.setdefault((l["handle"], l["lado"]), []).append(g)
    return {k: tuple(round(statistics.median(v), 4) for v in zip(*gs)) for k, gs in grupos.items()}


def geometria_padrao(lado: str, cfg: dict, produto: Optional[Produto] = None) -> Tuple[Tuple[float, float, float], str]:
    gp = cfg["geometria_padrao"]
    chave = lado
    if lado == "frente" and produto is not None:
        t = sem_acentos(texto_descricao(produto.corpo)).lower()
        if ("frente" in t or "frontal" in t) and "peito" not in t and "pequen" not in t and "costas" not in t:
            chave = "frente_grande"  # só frente, descrição sem "peito": arte grande centralizada
    g = gp.get(chave, gp[lado])
    return (float(g["largura_rel"]), float(g["topo_rel"]), float(g.get("centro_x_rel", 0.0))), "padrao"


def planejar(proj: Projeto, mapa_linhas: List[LinhaMapa], mk: ResultadoMockups,
             produtos: Optional[List[Produto]] = None, filtro_produtos: Optional[List[str]] = None,
             filtro_cores: Optional[List[str]] = None, limite: Optional[int] = None, forcar: bool = False,
             previa: bool = False, analise: Optional[List[dict]] = None) -> List[Tarefa]:
    cfg = proj.cfg
    medidas = geometrias_da_analise(analise or [])
    mapa: Dict[str, List[LinhaMapa]] = {}
    for l in mapa_linhas:
        mapa.setdefault(l.handle, []).append(l)
    if produtos is None:
        # sem CSV: produtos e cores vêm do próprio mapa
        produtos = []
        for h, ls in mapa.items():
            cores = []
            for l in ls:
                if l.cor and l.cor not in cores:
                    cores.append(l.cor)
            if not cores:
                cores = [c for c in sorted({c for c, _ in mk.mockups})]
            produtos.append(Produto(h, ls[0].NOME or h, ls[0].NOME or h.upper(), "T-Shirt", "active", "", cores))
    filtro_n = {_norm(x) for x in (filtro_produtos or [])}
    filtro_c = {_norm(x) for x in (filtro_cores or [])}
    pasta_saida = proj.pasta("saida_previa" if previa else "saida")
    pasta_web = proj.pasta("saida_web")
    pasta_transp = proj.raiz / cfg["pastas"].get("saida_transparente", "saida_transparente")
    tarefas: List[Tarefa] = []
    n_prod = 0
    for p in produtos:
        if filtro_n and not ({_norm(p.nome), _norm(p.handle), _norm(p.titulo)} & filtro_n):
            continue
        if limite is not None and n_prod >= limite:
            break
        n_prod += 1
        ls = mapa.get(p.handle, [])
        for cor in p.cores:
            if filtro_c and _norm(cor) not in filtro_c and _norm(getattr(cor_por_nome(cor, cfg), "codigo", "")) not in filtro_c:
                continue
            info = cor_por_nome(cor, cfg)
            codigo = info.codigo if info else _norm(cor).upper()[:6]
            t = Tarefa(p.handle, p.nome, cor, codigo)
            tarefas.append(t)
            if info is None or info.especial or not info.ativa or not (mk.tem(cor, "frente") and mk.tem(cor, "costas")):
                t.status = "sem_mockup"
                t.observacao = (f"cor '{cor}' sem mockup liso (frente e costas)" if info is None or info.especial
                                or info.ativa else f"cor '{cor}' desativada no config.json")
                continue
            linhas = {lado: _linhas_do(p.handle, cor, lado, mapa) for lado in ("costas", "frente")}
            if not any(linhas.values()):
                t.status = "sem_estampa"
                t.observacao = "produto/cor sem linha no mapa.csv (rode o casar ou preencha à mão)"
                continue
            tem = {lado: bool(l and l.tem_estampa) for lado, l in linhas.items()}
            falta = [lado for lado, l in linhas.items() if l is not None and not l.eh_liso and not l.tem_estampa]
            if falta:
                # linha do mapa sem arquivo (e sem LISO): falta a arte; não gera um jogo incompleto
                t.status = "sem_estampa"
                t.observacao = ("falta a arte: " + " e ".join(falta) +
                                " (ponha o arquivo no mapa.csv ou escreva LISO em arquivo_estampa)")
                continue
            if not tem["costas"] and not tem["frente"]:
                t.status = "liso"
                t.observacao = "mapa marca os dois lados como lisos"
                continue
            nums = numeracao_lados(tem["costas"], tem["frente"], cfg)
            vistas = [(lado, n) for lado, n in nums.items()]
            if tem["costas"] and mk.tem(cor, "close-costas"):
                vistas.append(("close-costas", 3))
            for vista, n in sorted(vistas, key=lambda v: v[1]):
                lado = "costas" if vista == "close-costas" else vista
                linha = linhas.get(lado)
                est = _resolver_estampa(proj, linha) if (linha and tem[lado]) else None
                geo, origem = None, ""
                if est is not None:
                    g = linha.geometria()
                    man = (cfg.get("geometria_manual", {}).get(p.handle) or cfg.get("geometria_manual", {}).get(p.nome)
                           or {}).get(lado)
                    if man:
                        geo, origem = (float(man["largura_rel"]), float(man["topo_rel"]),
                                       float(man.get("centro_x_rel", 0.0))), "calibrador"
                    elif g is not None:
                        geo, origem = g, (linha.origem or "mapa")
                    else:
                        g = geometria_do_produto(ls, lado)
                        if g is not None:
                            geo, origem = g, "mediana_produto"
                        elif (p.handle, lado) in medidas:
                            geo, origem = medidas[(p.handle, lado)], "analise"
                        else:
                            geo, origem = geometria_padrao(lado, cfg, p)
                    aj = cfg.get("ajuste_global", {})
                    if aj:
                        geo = (round(geo[0] * float(aj.get("escala", 1.0)), 4),
                               round(geo[1] + float(aj.get("deslocar_topo_rel", 0.0)), 4), geo[2])
                nome_v = NOME_VISTA_SAIDA[vista]
                arq = nome_arquivo_saida(p.nome, codigo, n, nome_v, "png", cfg)
                v = Vista(vista, n, str(mk.caminho(cor, vista)), str(mk.caminho(cor, "costas")),
                          str(est) if est else None, geo, origem,
                          str(pasta_saida / p.nome / arq),
                          "" if previa else str(pasta_web / arq.replace(".png", ".jpg")),
                          "" if previa else str(pasta_transp / p.nome / arq))
                if est is not None and not Path(est).exists():
                    v.status = "sem_estampa"
                    v.observacao = f"arquivo da estampa não encontrado: {est}"
                elif not forcar and Path(v.arquivo_png).exists():
                    v.status = "pulado"
                    v.observacao = "já existe (use --forcar para refazer)"
                t.vistas.append(v)
    return tarefas


def _norm(s: str) -> str:
    return "".join(ch for ch in sem_acentos(str(s)).lower() if ch.isalnum())


# ---------------------------------------------------------------------------
# Execução (um processo por worker; cada worker guarda mockups em cache)
# ---------------------------------------------------------------------------

_CACHE: Dict[tuple, object] = {}
_ESTAMPAS: Dict[str, Image.Image] = {}


def _mockup(caminho: str, cfg: dict, lado_max: Optional[int], torso_manual: Optional[dict] = None):
    from compositor import preparar_mockup
    chave = ("mk", caminho, lado_max)
    if chave not in _CACHE:
        if len(_CACHE) > 24:
            _CACHE.clear()
        _CACHE[chave] = preparar_mockup(caminho, cfg, torso_manual, lado_max)
    return _CACHE[chave]


def _estampa(caminho: str, cfg: dict, pasta_cache: Optional[Path] = None) -> Image.Image:
    """Arte pronta (fundo removido, bordas cortadas). Guarda em disco: tirar o fundo de um JPG leva segundos."""
    from imagem import carregar_estampa
    if caminho not in _ESTAMPAS:
        if len(_ESTAMPAS) > 16:
            _ESTAMPAS.clear()
        arq = None
        if pasta_cache is not None:
            import hashlib
            st = Path(caminho).stat()
            chave = hashlib.sha1(f"{Path(caminho).resolve()}|{st.st_size}|{int(st.st_mtime)}|"
                                 f"{cfg.get('fundo_estampa', {})}".encode()).hexdigest()[:20]
            arq = pasta_cache / f"{chave}.png"
            if arq.exists():
                try:
                    with Image.open(arq) as im:
                        _ESTAMPAS[caminho] = im.convert("RGBA")
                    return _ESTAMPAS[caminho]
                except Exception:
                    pass
        im = carregar_estampa(caminho, cfg)[0]
        if arq is not None:
            try:
                arq.parent.mkdir(parents=True, exist_ok=True)
                tmp = arq.with_name(arq.stem + f".{os.getpid()}.tmp.png")
                im.save(tmp, compress_level=1)
                os.replace(tmp, arq)
            except OSError:
                pass
        _ESTAMPAS[caminho] = im
    return _ESTAMPAS[caminho]


def caixa_no_mockup(torso, geo: Tuple[float, float, float], aspecto: float) -> Tuple[float, float, float, float]:
    from imagem import caixa_da_geometria
    return caixa_da_geometria(torso, geo[0], geo[1], geo[2], aspecto)


def renderizar_vista(tarefa: Tarefa, v: Vista, cfg: dict, raiz: str, previa: bool) -> Tuple[Image.Image, Optional[Image.Image]]:
    """Gera a imagem de uma vista (sem salvar). Retorna (final, master transparente)."""
    from compositor import MockupPreparado, aplicar_estampa, enquadrar, preparar_mockup
    from imagem import Torso
    lado_max = int(cfg["saida"].get("previa_lado_max", 900)) if previa else None
    lado_saida = int(cfg["saida"].get("previa_lado", 700)) if previa else int(cfg["enquadramento"].get("lado", 2048))
    manuais = cfg["mockups"].get("torso_manual", {})
    if v.vista == "close-costas":
        costas = _mockup(v.mockup_costas, cfg, lado_max, manuais.get(Path(v.mockup_costas).name))
        reg = registro_em_cache(Path(v.mockup_costas), Path(v.mockup),
                                Path(raiz) / cfg["pastas"].get("analise", "analise") / "registro_close.json",
                                cfg["mockups"].get("registro_manual", {}).get(Path(v.mockup).name))
        chave = ("close", v.mockup, lado_max)
        if chave not in _CACHE:
            from imagem import carregar_imagem
            im = carregar_imagem(v.mockup)
            s_close = 1.0
            if lado_max and max(im.size) > lado_max:
                s_close = lado_max / float(max(im.size))
            # tronco das costas (px originais) -> close (px originais) -> escala de trabalho
            tc = costas.torso
            k = 1.0 / costas.escala

            def mapa_pt(x, y):
                X, Y = reg.costas_para_close(x * k, y * k)
                return X * s_close, Y * s_close
            x0, top = mapa_pt(tc.x0, tc.topo)
            x1, base = mapa_pt(tc.x1, tc.base)
            _, ax = mapa_pt(tc.x0, tc.axila)
            W, H = round(im.size[0] * s_close), round(im.size[1] * s_close)
            torso_c = Torso(x0, x1, top, base, ax, W, H)
            _CACHE[chave] = preparar_mockup(im, cfg, lado_max=lado_max, torso_de=torso_c)
        mk = _CACHE[chave]
        det = reg.escala * (mk.escala / costas.escala)
    else:
        mk = _mockup(v.mockup, cfg, lado_max, manuais.get(Path(v.mockup).name))
        det = 1.0
    foco_y = None
    if v.estampa:
        art = _estampa(v.estampa, cfg, Path(raiz) / cfg["pastas"].get("analise", "analise") / "estampas_prontas")
        aspecto = art.size[1] / float(art.size[0])
        caixa = caixa_no_mockup(mk.torso, v.geometria, aspecto)
        im = aplicar_estampa(mk, art, caixa, cfg, escala_detalhe=det)
        foco_y = caixa[1] + caixa[3] / 2.0
    else:
        im = mk.imagem.copy()
    return enquadrar(im, cfg, lado_saida, foco_y=foco_y, eh_close=(v.vista == "close-costas"))


def _salvar(final: Image.Image, master: Optional[Image.Image], v: Vista, cfg: dict) -> None:
    s = cfg["saida"]
    Path(v.arquivo_png).parent.mkdir(parents=True, exist_ok=True)
    tmp = v.arquivo_png + ".tmp.png"
    final.save(tmp, compress_level=int(s.get("png_compressao", 6)))
    os.replace(tmp, v.arquivo_png)  # nunca deixa arquivo pela metade
    if v.arquivo_web:
        Path(v.arquivo_web).parent.mkdir(parents=True, exist_ok=True)
        web = final.convert("RGB")
        lm = int(s.get("web_lado_max", 2048))
        if max(web.size) > lm:
            web.thumbnail((lm, lm), Image.LANCZOS)
        web.save(v.arquivo_web, quality=int(s.get("web_qualidade", 88)), optimize=True, progressive=True,
                 subsampling=0)
    if v.arquivo_transparente and master is not None and cfg["enquadramento"].get("fundo") != "transparente":
        Path(v.arquivo_transparente).parent.mkdir(parents=True, exist_ok=True)
        master.save(v.arquivo_transparente, compress_level=int(s.get("png_compressao", 6)))


def executar_tarefa(tarefa: Tarefa, cfg: dict, raiz: str, previa: bool) -> Tarefa:
    for v in tarefa.vistas:
        if v.status:
            continue
        t0 = time.time()
        try:
            final, master = renderizar_vista(tarefa, v, cfg, raiz, previa)
            _salvar(final, master, v, cfg)
            v.status = "ok" if v.estampa else "liso"
            if v.estampa is None:
                v.observacao = "lado sem estampa (frente lisa)"
        except Exception as e:  # um arquivo ruim não para o lote
            v.status = "erro"
            v.observacao = f"{type(e).__name__}: {e}"
            if os.environ.get("PALLACIO_DEBUG"):
                traceback.print_exc()
        v.observacao = (v.observacao + f" [{time.time() - t0:.1f}s]").strip()
    return tarefa


def executar(tarefas: List[Tarefa], cfg: dict, raiz: Path, previa: bool, workers: int = 1, progresso=None) -> List[Tarefa]:
    pendentes = [t for t in tarefas if not t.status and any(not v.status for v in t.vistas)]
    feitas = [t for t in tarefas if t not in pendentes]
    # alinhamentos close->costas: calcula uma vez aqui (cache em disco) antes de dividir entre processos
    pares = {(v.mockup_costas, v.mockup) for t in pendentes for v in t.vistas
             if v.vista == "close-costas" and not v.status}
    for costas, close in sorted(pares):
        try:
            registro_em_cache(Path(costas), Path(close), raiz / cfg["pastas"].get("analise", "analise") / "registro_close.json",
                              cfg["mockups"].get("registro_manual", {}).get(Path(close).name))
        except Exception:
            pass  # o erro aparece na vista, com a mensagem certa
    if workers <= 1 or len(pendentes) <= 1:
        for i, t in enumerate(pendentes, 1):
            feitas.append(executar_tarefa(t, cfg, str(raiz), previa))
            if progresso:
                progresso(i, len(pendentes), t)
    else:
        # agrupa por cor: cada worker tende a reaproveitar o mesmo mockup do cache
        pendentes.sort(key=lambda t: (t.cor, t.handle))
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(executar_tarefa, t, cfg, str(raiz), previa): t for t in pendentes}
            for i, f in enumerate(as_completed(futs), 1):
                try:
                    t = f.result()
                except Exception as e:
                    t = futs[f]
                    for v in t.vistas:
                        if not v.status:
                            v.status, v.observacao = "erro", f"{type(e).__name__}: {e}"
                feitas.append(t)
                if progresso:
                    progresso(i, len(pendentes), t)
    ordem = {id(t): i for i, t in enumerate(tarefas)}
    feitas.sort(key=lambda t: ordem.get(id(t), 0))
    return feitas


def linhas_relatorio(tarefas: List[Tarefa]) -> List[dict]:
    out = []
    for t in tarefas:
        base = {"handle": t.handle, "NOME": t.nome, "cor": t.cor, "codigo": t.codigo}
        if t.status or not t.vistas:
            out.append({**base, "status": t.status or "sem_estampa", "observacao": t.observacao})
            continue
        for v in t.vistas:
            g = v.geometria or ("", "", "")
            seg = ""
            obs = v.observacao
            if obs.endswith("s]") and "[" in obs:
                seg = obs[obs.rindex("[") + 1:-2]
                obs = obs[:obs.rindex("[")].strip()
            out.append({**base, "vista": NOME_VISTA_SAIDA[v.vista], "numero": f"{v.numero:02d}",
                        "arquivo": Path(v.arquivo_png).name, "status": v.status,
                        "estampa": Path(v.estampa).name if v.estampa else "",
                        "origem_geometria": v.origem_geometria, "largura_rel": g[0], "topo_rel": g[1],
                        "centro_x_rel": g[2], "segundos": seg, "observacao": obs})
    return out
