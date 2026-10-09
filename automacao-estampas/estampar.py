"""Comando estampar: mapa.csv + mockups lisos + estampas -> imagens finais padronizadas.

Planejamento (o que gerar) é separado da execução (pixels), para rodar em paralelo e para os testes.
"""
from __future__ import annotations

import csv
import math
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

NOME_VISTA_SAIDA = {"costas": "costas", "frente": "frente", "close-costas": "close", "costas-inclinada": "inclinada"}
VISTAS_DAS_COSTAS = ("close-costas", "costas-inclinada")  # vistas extras que mostram a arte das costas


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
    razao_loja: Optional[float] = None   # largura/altura do tronco nas fotos da loja (ajuste de tamanho)
    checar_residuo: bool = True          # confere restos de fundo na arte antes de estampar
    ajuste_tinta: str = ""               # coluna ajuste_tinta do mapa.csv (cor da tinta -> cor da loja)


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


def _pede_revisao(linha: LinhaMapa) -> bool:
    """Linha com arte que o casar marcou para revisar (fundo sujo, pouca confiança...). Manual nunca."""
    if linha is None or (linha.origem or "").strip().lower() == "manual":
        return False
    return (linha.revisar or "").strip().lower() in ("sim", "s", "yes", "x", "1")


def razao_tronco_loja(analise: List[dict], cfg: dict) -> Optional[float]:
    """Largura/altura do tronco nas fotos atuais da loja (mediana). O mockup novo é mais estreito para
    a altura dele; a arte é dimensionada pela média geométrica das escalas pela largura e pela altura."""
    rs = []
    for l in analise:
        try:
            w = float(l["torso_x1"]) - float(l["torso_x0"])
            h = float(l["torso_base"]) - float(l["torso_topo"])
        except (KeyError, TypeError, ValueError):
            continue
        if w > 0 and h > 0 and 0.3 < w / h < 0.9:
            rs.append(w / h)
    t = cfg.get("tamanho", {})
    if len(rs) >= 4:
        return round(statistics.median(rs), 4)
    v = t.get("razao_tronco_loja")
    return float(v) if v else None


def fator_tamanho(razao_loja: Optional[float], torso, cfg: dict) -> float:
    """Escala extra da largura da arte: (razão da loja / razão do mockup) ** peso_altura."""
    if not razao_loja or torso is None or torso.altura <= 0:
        return 1.0
    peso = float(cfg.get("tamanho", {}).get("peso_altura", 0.5))
    f = (razao_loja / (torso.largura / torso.altura)) ** peso
    return float(min(1.25, max(0.8, f)))


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
             previa: bool = False, analise: Optional[List[dict]] = None,
             incluir_revisar: bool = False) -> List[Tarefa]:
    cfg = proj.cfg
    medidas = geometrias_da_analise(analise or [])
    razao_loja = razao_tronco_loja(analise or [], cfg)
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
            # cores "camiseta / estampa" usam o mockup da cor indicada em "mockup"
            cor_mk = (info.mockup if info is not None and info.mockup else cor)
            if (info is None or (info.especial and not info.mockup) or not info.ativa
                    or not (mk.tem(cor_mk, "frente") and mk.tem(cor_mk, "costas"))):
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
            # frente sem arquivo de arte: sai a frente lisa (só a cor), para todo produto ter a foto da frente
            if "frente" in falta and cfg.get("estampar", {}).get("frente_sem_arte", "liso") == "liso":
                falta.remove("frente")
            ecfg = cfg.get("estampar", {})
            if falta and (ecfg.get("so_cores_completas", False) or not (tem["costas"] or tem["frente"])):
                # config pede só jogos completos (ou não há arte nenhuma): não gera nada desta cor
                t.status = "sem_estampa"
                t.observacao = ("falta a arte: " + " e ".join(falta) +
                                " (ponha o arquivo no mapa.csv ou escreva LISO em arquivo_estampa)")
                continue
            if not tem["costas"] and not tem["frente"]:
                t.status = "liso"
                t.observacao = "mapa marca os dois lados como lisos"
                continue
            # numeração prevista: o lado que só está sem arquivo continua com o número dele
            previsto = {lado: tem[lado] or lado in falta for lado in tem}
            nums = numeracao_lados(previsto["costas"], previsto["frente"], cfg)
            vistas = [(lado, n) for lado, n in nums.items()]
            # fotos extras das costas: inclinada (03) e, se ligado no config, o close
            extra = 3
            if tem["costas"] and mk.tem(cor_mk, "costas-inclinada"):
                vistas.append(("costas-inclinada", extra))
                extra += 1
            if tem["costas"] and ecfg.get("usar_close", False) and mk.tem(cor_mk, "close-costas"):
                vistas.append(("close-costas", extra))
            for vista, n in sorted(vistas, key=lambda v: v[1]):
                lado = "costas" if vista in VISTAS_DAS_COSTAS else vista
                linha = linhas.get(lado)
                nome_v = NOME_VISTA_SAIDA[vista]
                arq = nome_arquivo_saida(p.nome, codigo, n, nome_v, "png", cfg)
                if lado in falta:
                    v = Vista(vista, n, str(mk.caminho(cor_mk, vista)), str(mk.caminho(cor_mk, "costas")), None, None, "",
                              str(pasta_saida / p.nome / arq), "", "")
                    v.status = "sem_estampa"
                    v.observacao = (f"falta a arte {'das costas' if lado == 'costas' else 'da frente'} "
                                    "(ponha o arquivo no mapa.csv ou escreva LISO); os outros lados foram gerados")
                    t.vistas.append(v)
                    continue
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
                    # tamanho das costas (01 e 03): "escala_costas" no config (1.0 = igual à loja)
                    if lado == "costas":
                        ec = float(ecfg.get("escala_costas", 0.92))
                        if abs(ec - 1.0) > 1e-6:
                            geo = (round(geo[0] * ec, 4), geo[1], geo[2])
                    aj = cfg.get("ajuste_global", {})
                    if aj:
                        geo = (round(geo[0] * float(aj.get("escala", 1.0)), 4),
                               round(geo[1] + float(aj.get("deslocar_topo_rel", 0.0)), 4), geo[2])
                v = Vista(vista, n, str(mk.caminho(cor_mk, vista)), str(mk.caminho(cor_mk, "costas")),
                          str(est) if est else None, geo, origem,
                          str(pasta_saida / p.nome / arq),
                          "" if previa else str(pasta_web / arq.replace(".png", ".jpg")),
                          "" if previa else str(pasta_transp / p.nome / arq))
                v.razao_loja = razao_loja if origem != "calibrador" else None
                v.ajuste_tinta = (linha.ajuste_tinta or "") if linha is not None else ""
                v.checar_residuo = not incluir_revisar and not (linha is not None and
                                                                (linha.origem or "").strip().lower() == "manual")
                if est is not None and _pede_revisao(linha) and not incluir_revisar:
                    v.status = "revisar"
                    v.observacao = ("o mapa.csv pede revisão desta arte (" + (linha.observacao or
                                    f"confiança {linha.confianca}") + "). Confira no revisao.html; se estiver certa, "
                                    "troque revisar para nao no mapa.csv (ou rode com --incluir-revisar)")
                elif est is not None and not Path(est).exists():
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


_RESIDUO: Dict[str, Optional[str]] = {}


def residuo_da_estampa(caminho: str, cfg: dict, raiz: str) -> Optional[str]:
    """Restos de fundo na arte pronta (guardado por processo)."""
    from imagem import residuo_de_fundo
    if caminho not in _RESIDUO:
        art = _estampa(caminho, cfg, Path(raiz) / cfg["pastas"].get("analise", "analise") / "estampas_prontas")
        _RESIDUO[caminho] = residuo_de_fundo(art)
    return _RESIDUO[caminho]


def caixa_no_mockup(torso, geo: Tuple[float, float, float], aspecto: float) -> Tuple[float, float, float, float]:
    from imagem import caixa_da_geometria
    return caixa_da_geometria(torso, geo[0], geo[1], geo[2], aspecto)


def renderizar_vista(tarefa: Tarefa, v: Vista, cfg: dict, raiz: str, previa: bool) -> Tuple[Image.Image, Optional[Image.Image]]:
    """Gera a imagem de uma vista (sem salvar). Retorna (final, master transparente)."""
    from compositor import MockupPreparado, aplicar_estampa, enquadrar, preparar_mockup
    from imagem import Torso, ajustar_tinta, ler_ajuste_tinta
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
        torso_ref = costas.torso
    elif v.vista == "costas-inclinada":
        return _renderizar_inclinada(v, cfg, raiz, lado_max, lado_saida, manuais)
    else:
        mk = _mockup(v.mockup, cfg, lado_max, manuais.get(Path(v.mockup).name))
        det = 1.0
        torso_ref = mk.torso
    foco_y = None
    if v.estampa:
        art = _estampa(v.estampa, cfg, Path(raiz) / cfg["pastas"].get("analise", "analise") / "estampas_prontas")
        aj = ler_ajuste_tinta(v.ajuste_tinta)
        if aj is not None:
            chave_aj = ("ajuste", v.estampa, aj)
            if chave_aj not in _CACHE:
                _CACHE[chave_aj] = ajustar_tinta(art, aj)
            art = _CACHE[chave_aj]
        aspecto = art.size[1] / float(art.size[0])
        geo = v.geometria
        f = fator_tamanho(v.razao_loja, torso_ref, cfg)
        if abs(f - 1.0) > 1e-3:
            geo = (geo[0] * f, geo[1], geo[2])
        caixa = caixa_no_mockup(mk.torso, geo, aspecto)
        im = aplicar_estampa(mk, art, caixa, cfg, escala_detalhe=det)
        foco_y = caixa[1] + caixa[3] / 2.0
    else:
        im = mk.imagem.copy()
    return enquadrar(im, cfg, lado_saida, foco_y=foco_y, eh_close=(v.vista == "close-costas"))


def _arte_da_vista(v: Vista, cfg: dict, raiz: str) -> Image.Image:
    from imagem import ajustar_tinta, ler_ajuste_tinta
    art = _estampa(v.estampa, cfg, Path(raiz) / cfg["pastas"].get("analise", "analise") / "estampas_prontas")
    aj = ler_ajuste_tinta(v.ajuste_tinta)
    if aj is not None:
        chave_aj = ("ajuste", v.estampa, aj)
        if chave_aj not in _CACHE:
            _CACHE[chave_aj] = ajustar_tinta(art, aj)
        art = _CACHE[chave_aj]
    return art


def _coef_perspectiva(destino, origem):
    """Coeficientes do PIL (PERSPECTIVE) que levam cada ponto de destino ao ponto de origem."""
    import numpy as np
    m, b = [], []
    for (X, Y), (x, y) in zip(destino, origem):
        m.append([X, Y, 1, 0, 0, 0, -x * X, -x * Y])
        m.append([0, 0, 0, X, Y, 1, -y * X, -y * Y])
        b += [x, y]
    return tuple(np.linalg.solve(np.array(m, float), np.array(b, float)))


def _renderizar_inclinada(v: Vista, cfg: dict, raiz: str, lado_max, lado_saida, manuais):
    """Costas inclinada: calcula a caixa da estampa nas costas retas e leva para a foto inclinada
    pelo mesmo giro/escala da peça, então estampa com a luz e as dobras do mockup inclinado."""
    import numpy as np
    from compositor import aplicar_estampa, enquadrar, redimensionar_premultiplicado
    from mockups import registro_inclinada_em_cache
    costas = _mockup(v.mockup_costas, cfg, lado_max, manuais.get(Path(v.mockup_costas).name))
    mk = _mockup(v.mockup, cfg, lado_max, manuais.get(Path(v.mockup).name))
    if not v.estampa:
        return enquadrar(mk.imagem.copy(), cfg, lado_saida)
    reg = registro_inclinada_em_cache(Path(v.mockup_costas), Path(v.mockup),
                                      Path(raiz) / cfg["pastas"].get("analise", "analise") / "registro_inclinada.json",
                                      cfg["mockups"].get("registro_manual", {}).get(Path(v.mockup).name))
    art = _arte_da_vista(v, cfg, raiz)
    geo = v.geometria
    f = fator_tamanho(v.razao_loja, costas.torso, cfg)
    if abs(f - 1.0) > 1e-3:
        geo = (geo[0] * f, geo[1], geo[2])
    x, y, w, h = caixa_no_mockup(costas.torso, geo, art.size[1] / float(art.size[0]))
    # a perspectiva da foto inclinada alarga o corpo; "escala_inclinada" ajusta a estampa só nela,
    # mantendo o topo (1.0 = mesmo tamanho proporcional da foto 01)
    ecfg = cfg.get("estampar", {})
    ei = float(ecfg.get("escala_inclinada", 0.924))
    x, y, w, h = x + w * (1 - ei) / 2.0, y, w * ei, h * ei
    # "subir_inclinada": sobe a estampa na foto inclinada (fração da altura do tronco)
    y -= float(ecfg.get("subir_inclinada", 0.015)) * costas.torso.altura
    # px de trabalho das costas -> px do arquivo -> px do arquivo inclinado -> px de trabalho da inclinada
    kc, ki = costas.escala, mk.escala
    # os 4 cantos da caixa (px das costas -> px do arquivo inclinado -> px de trabalho da inclinada)
    cantos = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    quad = []
    for px_, py_ in cantos:
        X, Y = reg.ponto(px_ / kc, py_ / kc)
        quad.append((X * ki, Y * ki))
    # "girar_inclinada": giro extra da estampa (graus, positivo = anti-horário), em volta do centro dela
    gx = float(ecfg.get("girar_inclinada", 7.0))
    if gx:
        mx, my = sum(q[0] for q in quad) / 4.0, sum(q[1] for q in quad) / 4.0
        tg = math.radians(gx)
        cg, sg = math.cos(tg), math.sin(tg)
        quad = [(mx + cg * (qx_ - mx) + sg * (qy_ - my), my - sg * (qx_ - mx) + cg * (qy_ - my)) for qx_, qy_ in quad]
    # "mover_inclinada": desloca a estampa na horizontal da foto (fração da largura da imagem; negativo = esquerda)
    mv = float(ecfg.get("mover_inclinada", -0.011)) * mk.rgb.shape[1]
    # "mover_inclinada_vertical": fração da altura da foto (positivo = para cima)
    mvv = float(ecfg.get("mover_inclinada_vertical", 0.002)) * mk.rgb.shape[0]
    if mv or mvv:
        quad = [(qx_ + mv, qy_ - mvv) for qx_, qy_ in quad]
    # estampa larga: encolhe em volta do centro até os cantos ficarem dentro da peça (com folga)
    masc = mk.mascara
    Hm, Wm = masc.shape
    folga = max(2, int(0.012 * Wm))

    def dentro(px_, py_):
        xi, yi = int(round(px_)), int(round(py_))
        if not (folga <= xi < Wm - folga and folga <= yi < Hm - folga):
            return False
        return bool(masc[yi - folga:yi + folga + 1, xi - folga:xi + folga + 1].all())

    mx, my = sum(q[0] for q in quad) / 4.0, sum(q[1] for q in quad) / 4.0
    for _ in range(25):
        if all(dentro(qx_, qy_) for qx_, qy_ in quad):
            break
        quad = [(mx + 0.97 * (qx_ - mx), my + 0.97 * (qy_ - my)) for qx_, qy_ in quad]
    qx = [q[0] for q in quad]
    qy = [q[1] for q in quad]
    bx0, by0 = math.floor(min(qx)), math.floor(min(qy))
    W2, H2 = int(math.ceil(max(qx))) - bx0 + 1, int(math.ceil(max(qy))) - by0 + 1
    # arte no tamanho aproximado do destino (pré-multiplicada) e levada ao quadrilátero em perspectiva
    lw = max(1, round(math.hypot(quad[1][0] - quad[0][0], quad[1][1] - quad[0][1])))
    lh = max(1, round(math.hypot(quad[3][0] - quad[0][0], quad[3][1] - quad[0][1])))
    rgb, a = redimensionar_premultiplicado(art, lw, lh)
    arr = np.dstack([np.clip(rgb * 255.0, 0, 255), np.clip(a * 255.0, 0, 255)]).astype(np.uint8)
    destino = [(qx_ - bx0, qy_ - by0) for qx_, qy_ in quad]
    origem = [(0, 0), (lw, 0), (lw, lh), (0, lh)]
    coef = _coef_perspectiva(destino, origem)
    girada = Image.fromarray(arr, "RGBa").transform((W2, H2), Image.PERSPECTIVE, coef, Image.BICUBIC).convert("RGBA")
    cy = sum(qy) / 4.0
    caixa = (float(bx0), float(by0), float(W2), float(H2))
    im = aplicar_estampa(mk, girada, caixa, cfg, escala_detalhe=1.0)
    return enquadrar(im, cfg, lado_saida, foco_y=cy)


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
            if v.estampa and v.checar_residuo and cfg.get("estampar", {}).get("verificar_residuo", True):
                prob = residuo_da_estampa(v.estampa, cfg, raiz)
                if prob:
                    v.status = "revisar"
                    v.observacao = (prob + ". Use uma versão da arte com fundo transparente (PNG) ou limpe o "
                                    "fundo; para gerar assim mesmo, ponha origem=manual na linha do mapa.csv")
                    continue
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
