"""Comando casar: acha a arte de cada camiseta x cor x lado e preenche o mapa.csv.

Entradas
  * dados/inventario.csv — inventário conferido à mão de todas as artes das pastas do dono
    (produto, lado, para qual camisa: clara = Branca/Off White, escura = Preta/Azul Marinho, todas, ?);
  * as pastas de artes (varridas de novo: arquivos novos entram pelas pistas do nome da pasta/arquivo
    e pela comparação visual com as fotos atuais da loja);
  * analise.csv (do comando analisar): medidas da estampa nas fotos atuais e recorte para comparar.

Saídas
  * mapa.csv — uma linha por camiseta x cor x lado (costas/frente). Linhas com origem=manual nunca são
    sobrescritas; o resto é refeito a cada rodada (por isso: rode de novo depois do baixar + analisar).
  * revisao.html — foto atual x arte escolhida, com selo de confiança e as listas de pendências.
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import os
import statistics
import unicodedata
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image

from catalogo import (ErroUsuario, Produto, cor_por_nome, ler_catalogo, ler_csv_dicts, pistas_texto, sem_acentos,
                      texto_descricao)

AQUI = Path(__file__).resolve().parent
INVENTARIO_PADRAO = AQUI / "dados" / "inventario.csv"

COLUNAS_INVENTARIO = ["caminho", "fonte", "tipo", "produto", "produto_sugerido", "lado", "para_camisa",
                      "cor_especifica", "fundo", "qualidade", "largura", "altura", "tem_alpha", "aspecto_arte",
                      "tinta_l25", "tinta_l50", "tinta_l75", "hash_visual", "sha1", "duplicata_de",
                      "versao_preferida", "escolhida", "origem", "observacao", "usar_tambem"]

COLUNAS_MAPA_CASAR = ["handle", "NOME", "titulo", "cor", "lado", "arquivo_estampa", "para_camisa", "largura_rel",
                      "topo_rel", "centro_x_rel", "origem", "confianca", "revisar", "observacao", "ajuste_tinta"]

TIPOS_ARTE = {"estampa", "estampa_com_fundo"}
QUALIDADE_OK = {"", "ok", "n/a"}
LISO = "LISO"


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s or "")


def chave_titulo(s: str) -> str:
    return "".join(ch for ch in sem_acentos(nfc(s)).upper() if ch.isalnum())


# ---------------------------------------------------------------------------
# Inventário
# ---------------------------------------------------------------------------

def ler_inventario(caminho: Path) -> List[dict]:
    linhas = ler_csv_dicts(caminho)
    for l in linhas:
        for k in COLUNAS_INVENTARIO:
            l.setdefault(k, "")
        l["caminho"] = nfc(l["caminho"])
    return linhas


def fonte_de(caminho: str, cfg: dict) -> str:
    c = nfc(caminho)
    for f in cfg["casar"]["prioridade_fontes"]:
        if c == nfc(f) or c.startswith(nfc(f) + "/"):
            return f
    return c.split("/")[0] if "/" in c else ""


def _f(v, padrao: float = 0.0) -> float:
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return padrao


def chave_ordem(l: dict, cfg: dict) -> tuple:
    """Menor = melhor: versão preferida, PNG transparente, texto/fundo sem problema, fonte, resolução."""
    prio = cfg["casar"]["prioridade_fontes"]
    fonte = l.get("fonte") or fonte_de(l["caminho"], cfg)
    nome = sem_acentos(l["caminho"].split("/")[-1]).lower()
    return (
        1 if l.get("versao_preferida") == "nao" else 0,
        0 if l.get("qualidade", "") in QUALIDADE_OK else 1,
        0 if l.get("tem_alpha") == "sim" else 1,
        prio.index(fonte) if fonte in prio else len(prio),
        -(_f(l.get("largura")) * _f(l.get("altura"))),
        1 if ("copia" in nome or "copy" in nome) else 0,
        l["caminho"],
    )


def eh_arte(l: dict) -> bool:
    return l.get("tipo") in TIPOS_ARTE


def marcar_escolhidas(linhas: List[dict], cfg: dict) -> None:
    """escolhida = sim (melhor por produto+lado+para_camisa+cor_especifica) | alternativa | ''."""
    grupos: Dict[tuple, List[dict]] = defaultdict(list)
    for l in linhas:
        l["escolhida"] = ""
        if eh_arte(l) and l.get("produto") not in ("", "?") and l.get("versao_preferida") != "nao":
            grupos[(l["produto"], l["lado"], l["para_camisa"], l.get("cor_especifica", ""))].append(l)
    for ls in grupos.values():
        ls.sort(key=lambda l: chave_ordem(l, cfg))
        ls[0]["escolhida"] = "sim"
        for l in ls[1:]:
            l["escolhida"] = "alternativa"


# ---------------------------------------------------------------------------
# Ficha da arte: miniatura sem fundo, proporção, luminosidade da tinta, hash visual
# ---------------------------------------------------------------------------

def _lab_l(rgb: np.ndarray) -> np.ndarray:
    from imagem import rgb_para_lab
    return rgb_para_lab(rgb)[..., 0]


def dhash(rgba: Image.Image) -> str:
    """Hash visual (64 bits) da arte sobre cinza médio: tinta clara e tinta escura dão hashes diferentes."""
    base = Image.new("RGB", rgba.size, (128, 128, 128))
    base.paste(rgba.convert("RGB"), (0, 0), rgba.getchannel("A") if rgba.mode == "RGBA" else None)
    g = np.asarray(base.convert("L").resize((9, 8), Image.BILINEAR), np.float32)
    bits = (g[:, 1:] > g[:, :-1]).flatten()
    return "%016x" % int("".join("1" if b else "0" for b in bits), 2)


def hamming(a: str, b: str) -> int:
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except ValueError:
        return 64


def ficha_arte(caminho, lado_max: int = 512, cfg: Optional[dict] = None) -> Tuple[dict, Optional[Image.Image]]:
    """Abre a arte em tamanho reduzido, tira o fundo liso se não tiver transparência e mede.

    Retorna ({largura, altura, tem_alpha, fundo_removido, aspecto_arte, tinta_l25/50/75, hash_visual}, miniatura RGBA).
    """
    from imagem import carregar_imagem, recortar_alpha, remover_fundo, tem_transparencia
    im = carregar_imagem(caminho)
    info = {"largura": im.size[0], "altura": im.size[1], "tem_alpha": "sim" if tem_transparencia(im) else "nao",
            "fundo_removido": "nao"}
    pequena = im.copy()
    pequena.thumbnail((lado_max, lado_max), Image.LANCZOS)
    if info["tem_alpha"] == "nao":
        fcfg = (cfg or {}).get("fundo_estampa", {})
        pequena, rem = remover_fundo(pequena, float(fcfg.get("tolerancia", 16.0)),
                                     float(fcfg.get("buracos_area_max", 0.004)))
        info["fundo_removido"] = "sim" if rem else "nao"
    pequena = recortar_alpha(pequena.convert("RGBA"))
    a = np.asarray(pequena.getchannel("A"))
    rgb = np.asarray(pequena.convert("RGB"), np.float32) / 255.0
    tinta = a > 128
    if tinta.sum() < 10:
        tinta = a > 0
    L = _lab_l(rgb)[tinta] if tinta.any() else np.array([50.0])
    info.update({
        "aspecto_arte": round(pequena.size[1] / max(pequena.size[0], 1), 4),
        "tinta_l25": round(float(np.percentile(L, 25)), 1),
        "tinta_l50": round(float(np.percentile(L, 50)), 1),
        "tinta_l75": round(float(np.percentile(L, 75)), 1),
        "hash_visual": dhash(pequena),
    })
    return info, pequena


def _chave_cache(caminho: Path) -> str:
    st = caminho.stat()
    return hashlib.sha1(f"{nfc(str(caminho.resolve()))}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:20]


def _ficha_job(args) -> Tuple[str, Optional[dict], str]:
    caminho, pasta_cache, cfg = args
    caminho = Path(caminho)
    try:
        k = _chave_cache(caminho)
        mini = Path(pasta_cache) / f"{k}.png"
        meta = Path(pasta_cache) / f"{k}.json"
        if mini.exists() and meta.exists():
            return str(caminho), json.loads(meta.read_text(encoding="utf-8")), ""
        info, pequena = ficha_arte(caminho, cfg=cfg)
        mini.parent.mkdir(parents=True, exist_ok=True)
        pequena.save(mini)
        info["miniatura"] = str(mini)
        meta.write_text(json.dumps(info), encoding="utf-8")
        return str(caminho), info, ""
    except Exception as e:  # noqa: BLE001 — arquivo quebrado não pode parar o lote
        return str(caminho), None, f"{type(e).__name__}: {e}"


def fichas(caminhos: Sequence[Path], pasta_cache: Path, cfg: dict, workers: int = 4, progresso=None
           ) -> Tuple[Dict[str, dict], Dict[str, str]]:
    """Fichas (com cache em disco) de vários arquivos. Retorna ({caminho: ficha}, {caminho: erro})."""
    jobs = [(str(c), str(pasta_cache), cfg) for c in caminhos]
    ok, erros = {}, {}
    if workers > 1 and len(jobs) > 2:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            it = ex.map(_ficha_job, jobs, chunksize=1)
            for i, (c, info, err) in enumerate(it, 1):
                (ok.__setitem__(c, info) if info else erros.__setitem__(c, err))
                if progresso:
                    progresso(i, len(jobs), Path(c).name)
    else:
        for i, j in enumerate(jobs, 1):
            c, info, err = _ficha_job(j)
            (ok.__setitem__(c, info) if info else erros.__setitem__(c, err))
            if progresso:
                progresso(i, len(jobs), Path(c).name)
    return ok, erros


# ---------------------------------------------------------------------------
# Varredura das pastas e arquivos novos (fora do inventário)
# ---------------------------------------------------------------------------

_RAIZ_CACHE: Dict[tuple, Optional[Path]] = {}


def achar_raiz_arquivos(proj, informado: Optional[str] = None) -> Optional[Path]:
    """Pasta que contém as pastas de artes (CAMISETAS 100%, NOVAS...)."""
    k = (str(proj.raiz), str(proj.cfg["casar"].get("pasta_arquivos")), str(informado))
    if k not in _RAIZ_CACHE:
        _RAIZ_CACHE[k] = _achar_raiz_arquivos(proj, informado)
    return _RAIZ_CACHE[k]


def _achar_raiz_arquivos(proj, informado: Optional[str] = None) -> Optional[Path]:
    cfg = proj.cfg
    nomes = [nfc(p) for p in cfg["casar"]["pastas_estampas"]]
    cands = []
    if informado:
        cands.append(Path(informado).expanduser())
    if cfg["casar"].get("pasta_arquivos"):
        p = Path(cfg["casar"]["pasta_arquivos"]).expanduser()
        cands.append(p if p.is_absolute() else proj.raiz / p)
    cands += [proj.raiz, proj.raiz.parent]
    for c in cands:
        if c.is_dir():
            filhos = {nfc(x.name) for x in c.iterdir() if x.is_dir()}
            if any(n.split("/")[0] in filhos for n in nomes if n != "estampas"):
                return c.resolve()
    if informado:
        raise ErroUsuario(f"A pasta {informado} não tem as pastas de artes ({', '.join(nomes[:4])}).")
    return None


def escanear(raiz: Path, pastas: Iterable[str]) -> List[str]:
    """Caminhos relativos (NFC, com '/') de todos os arquivos das pastas (ignora ocultos e .DS_Store)."""
    out = []
    for p in pastas:
        base = raiz / p
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for f in sorted(filenames):
                if f.startswith(".") or f.lower() in ("thumbs.db", "desktop.ini"):
                    continue
                rel = Path(dirpath, f).relative_to(raiz).as_posix()
                out.append(nfc(rel))
    return sorted(set(out))


def sha1_arquivo(caminho: Path) -> str:
    h = hashlib.sha1()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def apelidos_de_pasta(inventario: List[dict]) -> Dict[str, str]:
    """Nome de pasta -> produto, aprendido do inventário (ex.: 'YATCH T-SHIRT' -> 'YACHT T-SHIRT')."""
    votos: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for l in inventario:
        if eh_arte(l) and l.get("produto") not in ("", "?"):
            partes = l["caminho"].split("/")[1:-1]
            for p in partes:
                votos[chave_titulo(p)][l["produto"]] += 1
    out = {}
    for k, v in votos.items():
        prod, n = max(v.items(), key=lambda kv: kv[1])
        if n >= 1 and n == sum(v.values()):
            out[k] = prod
    return out


def classificar_novo(rel: str, info: Optional[dict], titulos: Dict[str, str], apelidos: Dict[str, str],
                     cfg: dict) -> dict:
    """Linha de inventário para um arquivo que não estava no inventário (pistas pelo nome)."""
    from imagem import problema_formato
    nome = rel.split("/")[-1]
    t = sem_acentos(nome).lower()
    l = {k: "" for k in COLUNAS_INVENTARIO}
    l.update({"caminho": rel, "fonte": fonte_de(rel, cfg), "origem": "nome", "versao_preferida": "sim"})
    prob = problema_formato(Path(rel))
    if prob:
        l.update({"tipo": "nao_suportado", "observacao": prob})
        return l
    if info is None:
        l.update({"tipo": "ilegivel", "observacao": "não abriu"})
        return l
    l.update({k: str(info.get(k, "")) for k in ("largura", "altura", "tem_alpha", "aspecto_arte", "tinta_l25",
                                                 "tinta_l50", "tinta_l75", "hash_visual")})
    if "etiqueta" in t:
        l["tipo"] = "etiqueta"
    elif "mockup" in t:
        l["tipo"] = "mockup_outro"
    elif info.get("foto_loja"):
        l["tipo"] = "foto_loja"
    else:
        l["tipo"] = "estampa" if info.get("tem_alpha") == "sim" else "estampa_com_fundo"
    # produto: pastas (de dentro para fora) e nome do arquivo
    partes = rel.split("/")
    for p in reversed(partes[1:]):
        k = chave_titulo(Path(p).stem if p == nome else p)
        for sufixo in ("ESTAMPAS100", "ESTAMPAS", "ESTAMPA", "SOPRETA", "SOBRANCA"):
            k = k.replace(sufixo, "")
        if k in titulos:
            l["produto"] = titulos[k]
            break
        if k in apelidos:
            l["produto"] = apelidos[k]
            break
        achou = [tt for kk, tt in titulos.items() if len(kk) >= 6 and kk.replace("TSHIRT", "") and
                 kk.replace("TSHIRT", "") in k]
        if len(achou) == 1:
            l["produto"] = achou[0]
            break
    pista = pistas_texto(nome, cfg, l["produto"].replace(" T-SHIRT", ""))
    l["lado"] = pista["lado"] or "costas"
    if pista["cor"]:
        c = cor_por_nome(pista["cor"], cfg)
        l["para_camisa"] = "clara" if c and c.tom == "claro" else "escura"
    else:
        l["para_camisa"] = ink_para_camisa(info)
    l["observacao"] = "arquivo novo (fora do inventário): produto/lado/cor deduzidos do nome — conferir"
    return l


def ink_para_camisa(info: dict) -> str:
    """Pela luminosidade da tinta: escura -> camisa clara; clara -> camisa escura; colorida -> todas."""
    l25, l75 = _f(info.get("tinta_l25"), 50), _f(info.get("tinta_l75"), 50)
    if l75 < 45:
        return "clara"
    if l25 > 70:
        return "escura"
    return "?"


def parece_foto_loja(caminho: Path) -> bool:
    """Foto de produto da loja: quadrada, sem transparência, cantos cinza-claro e uma camiseta no meio."""
    try:
        with Image.open(caminho) as im:
            if abs(im.size[0] - im.size[1]) > 4 or min(im.size) < 700:
                return False
            if im.mode == "RGBA" and im.getextrema()[3][0] < 250:
                return False
            im.draft("RGB", (256, 256))
            a = np.asarray(im.convert("RGB").resize((64, 64)), np.float32)
    except Exception:
        return False
    cantos = np.concatenate([a[:4, :4].reshape(-1, 3), a[:4, -4:].reshape(-1, 3), a[-4:, :4].reshape(-1, 3),
                             a[-4:, -4:].reshape(-1, 3)])
    m = cantos.mean(0)
    cinza = 215 <= m.mean() <= 250 and np.ptp(m) < 8 and cantos.std() < 6
    centro = a[20:44, 24:40].reshape(-1, 3)
    return bool(cinza and np.abs(centro.mean(0) - m).max() > 6)


# ---------------------------------------------------------------------------
# Comparação visual com as fotos atuais da loja
# ---------------------------------------------------------------------------

LADO_ASS = 40


def _ass_lum(rgb: np.ndarray) -> np.ndarray:
    L = _lab_l(rgb.astype(np.float32) / 255.0)
    L = L - L.mean()
    n = np.linalg.norm(L)
    return L / n if n > 1e-6 else L


def _cor_tinta(rgb: np.ndarray, fundo: Tuple[int, int, int]) -> Optional[np.ndarray]:
    from imagem import rgb_para_lab
    lab = rgb_para_lab(rgb.astype(np.float32) / 255.0)
    fl = rgb_para_lab(np.array(fundo, np.float32)[None, None, :] / 255.0)[0, 0]
    d = np.linalg.norm(lab - fl, axis=-1)
    sel = d > 18
    if sel.sum() < 5:
        return None
    return np.median(lab[sel], axis=0)


def assinatura_foto(arquivo: str, bbox: Tuple[float, float, float, float], rgb_tecido) -> Optional[dict]:
    try:
        with Image.open(arquivo) as im:
            rec = im.convert("RGB").crop(tuple(int(round(v)) for v in bbox))
    except Exception:
        return None
    if rec.size[0] < 4 or rec.size[1] < 4:
        return None
    a = np.asarray(rec.resize((LADO_ASS, LADO_ASS), Image.BILINEAR), np.float32)
    return {"lum": _ass_lum(a), "cor": _cor_tinta(a, rgb_tecido), "aspecto": rec.size[1] / rec.size[0],
            "fundo": tuple(int(v) for v in rgb_tecido), "recorte": rec}


def assinatura_arte(mini: Image.Image, rgb_tecido) -> dict:
    base = Image.new("RGB", mini.size, tuple(int(v) for v in rgb_tecido))
    base.paste(mini.convert("RGB"), (0, 0), mini.getchannel("A"))
    a = np.asarray(base.resize((LADO_ASS, LADO_ASS), Image.BILINEAR), np.float32)
    return {"lum": _ass_lum(a), "cor": _cor_tinta(a, rgb_tecido), "aspecto": mini.size[1] / max(mini.size[0], 1)}


def similaridade(foto: dict, arte: dict) -> float:
    """0..1: forma (NCC da luminosidade) + cor da tinta + proporção. Separa tinta clara de tinta escura."""
    ncc = float((foto["lum"] * arte["lum"]).sum())
    if foto["cor"] is None or arte["cor"] is None:
        cor = 0.0
    else:
        cor = math.exp(-float(np.linalg.norm(foto["cor"] - arte["cor"])) / 25.0)
    asp = math.exp(-abs(math.log(max(foto["aspecto"], 1e-3) / max(arte["aspecto"], 1e-3))) * 4.0)
    return round(0.55 * max(ncc, 0.0) + 0.25 * cor + 0.20 * asp, 4)


def _resumo_tinta(lab: np.ndarray, fundo_lab: np.ndarray) -> Optional[dict]:
    """Tinta = pixels bem diferentes do tecido; usa a metade mais contrastante (o miolo dos traços,
    sem a borda misturada com o tecido)."""
    d = np.linalg.norm(lab - fundo_lab, axis=1)
    sel = d > 25
    if sel.sum() < 30:
        return None
    lab, d = lab[sel], d[sel]
    lab = lab[d >= np.median(d)]
    med = np.median(lab, axis=0)
    C = np.hypot(lab[:, 1], lab[:, 2])
    mono = float((np.linalg.norm(lab - med, axis=1) < 20).mean())
    return {"lab": med, "C": float(np.median(C)), "mono": mono}


def tinta_foto(arquivo: str, bbox: Tuple[float, float, float, float], rgb_tecido) -> Optional[dict]:
    """Cor típica da tinta na foto atual, dentro da caixa da estampa (no máximo 200 px)."""
    from imagem import rgb_para_lab
    try:
        with Image.open(arquivo) as im:
            rec = im.convert("RGB").crop(tuple(int(round(v)) for v in bbox))
    except Exception:
        return None
    if min(rec.size) < 24 or max(rec.size) < 60:
        return None  # estampa pequena demais na foto: a cor medida seria só borda borrada
    rec.thumbnail((200, 200), Image.BILINEAR)
    lab = rgb_para_lab(np.asarray(rec, np.float32) / 255.0).reshape(-1, 3)
    fl = rgb_para_lab(np.array(rgb_tecido, np.float32)[None, None, :] / 255.0)[0, 0]
    r = _resumo_tinta(lab, fl)
    if r is not None:
        r["tamanho"] = rec.size
    return r


def tinta_arte(mini: Image.Image, rgb_tecido, tamanho: Optional[Tuple[int, int]] = None) -> Optional[dict]:
    """Cor típica da tinta da arte, aplicada sobre o tecido no MESMO tamanho do recorte da foto
    (assim as duas medidas têm o mesmo borrão nas bordas dos traços)."""
    from imagem import rgb_para_lab
    m = mini.convert("RGBA")
    if tamanho:
        m = m.resize((max(1, int(tamanho[0])), max(1, int(tamanho[1]))), Image.LANCZOS)
    else:
        m.thumbnail((200, 200), Image.BILINEAR)
    base = Image.new("RGBA", m.size, tuple(int(v) for v in rgb_tecido) + (255,))
    base.alpha_composite(m)
    lab = rgb_para_lab(np.asarray(base.convert("RGB"), np.float32) / 255.0).reshape(-1, 3)
    fl = rgb_para_lab(np.array(rgb_tecido, np.float32)[None, None, :] / 255.0)[0, 0]
    return _resumo_tinta(lab, fl)


def extremos_tinta(caminho_mini: str) -> Optional[Tuple[str, str]]:
    """L* dos 10% mais escuros e dos 10% mais claros da tinta opaca da miniatura sem fundo."""
    try:
        with Image.open(caminho_mini) as m:
            arr = np.asarray(m.convert("RGBA"))
    except Exception:
        return None
    sel = arr[..., 3] > 200
    if sel.sum() < 30:
        return None
    L = _lab_l(arr[..., :3][sel].astype(np.float32)[None, :, :] / 255.0)[0]
    return f"{np.percentile(L, 10):.1f}", f"{np.percentile(L, 90):.1f}"


def comparar_tinta(foto: Optional[dict], arte: Optional[dict]) -> Optional[dict]:
    """Diferença da tinta (arte - foto) em Lab: claridade dL, saturação dC, distância dE."""
    if not foto or not arte:
        return None
    d = arte["lab"] - foto["lab"]
    return {"dL": float(d[0]), "da": float(d[1]), "db": float(d[2]), "dE": float(np.linalg.norm(d)),
            "dC": arte["C"] - foto["C"], "mono": min(foto["mono"], arte["mono"])}


def texto_ajuste(dif: dict) -> str:
    """Ajuste que leva a tinta da arte à cor medida na foto (deslocamento em Lab)."""
    return f"L={-dif['dL']:+.1f};a={-dif['da']:+.1f};b={-dif['db']:+.1f}"


# ---------------------------------------------------------------------------
# Regras de escolha
# ---------------------------------------------------------------------------

L_TECIDO = {"claro": 94.0, "escuro": 12.0}


def l_tecido(cor: str, cfg: dict) -> float:
    c = cor_por_nome(cor, cfg)
    if c is not None and c.rgb:
        return float(_lab_l(np.array(c.rgb, np.float32)[None, None, :] / 255.0)[0, 0])
    return L_TECIDO["claro" if (c is None or c.tom == "claro") else "escuro"]


def legivel(l: dict, cor: str, cfg: dict, estrito: bool = False) -> bool:
    """A tinta aparece nesta camisa? (usa tinta_l25/l50/l75 do inventário ou da ficha).

    estrito (arte que não foi feita para este tom): QUASE TODA a tinta (o quartil menos contrastante)
    precisa contrastar — texto escuro some na camisa preta mesmo que a arte tenha partes claras.
    normal (arte feita para este tom): basta a parte mais contrastante (quartil) aparecer.
    """
    if not l.get("tinta_l50"):
        return True  # sem medida: não dá para afirmar que some
    lt = l_tecido(cor, cfg)
    lim = float(cfg["casar"].get("contraste_minimo", 28.0))
    l25, l50, l75 = _f(l["tinta_l25"]), _f(l["tinta_l50"]), _f(l["tinta_l75"])
    # estrito: até a parte MENOS contrastante da tinta (10% mais escuros na camisa escura, 10% mais
    # claros na clara; sem essa medida, o quartil) tem de aparecer. Com a mediana, uma arte de texto
    # preto com um detalhe colorido passava e o texto sumia na camisa preta.
    l10 = _f(l["tinta_l10"]) if l.get("tinta_l10") not in (None, "") else l25
    l90 = _f(l["tinta_l90"]) if l.get("tinta_l90") not in (None, "") else l75
    if estrito == "mediana":  # arte sem tom definido (colorida): basta a maior parte contrastar
        l10, l90 = l50, l50
    if lt < 50:   # camisa escura: a tinta precisa ser mais clara que o tecido
        return (l10 if estrito else l75) - lt >= lim
    return lt - (l90 if estrito else l25) >= lim


def tom_da_cor(cor: str, cfg: dict) -> str:
    c = cor_por_nome(cor, cfg)
    return "claro" if c is None or c.tom == "claro" else "escuro"


def escolher_arte(cands: List[dict], cor: str, cfg: dict, visual: Optional[Dict[str, float]] = None
                  ) -> Tuple[Optional[dict], int, str]:
    """Escolhe a arte para uma cor. Retorna (linha, nível, observação).

    nível 1 = feita para esta cor; 2 = feita para o tom (clara/escura); 3 = 'todas'; 4 = '?' (indefinida);
    5 = só existe a do outro tom e continua legível (revisar); 0 = nada (falta / ilegível).
    """
    tom = tom_da_cor(cor, cfg)
    alvo = "clara" if tom == "claro" else "escura"
    oposto = "escura" if alvo == "clara" else "clara"
    niveis: Dict[int, List[dict]] = defaultdict(list)
    for l in cands:
        ce = l.get("cor_especifica", "")
        pc = l.get("para_camisa", "")
        if ce and ce == cor:
            niveis[1].append(l)
        elif pc == alvo and not ce:
            niveis[2].append(l)
        elif pc == alvo:
            niveis[2].append(dict(l, _outra_cor=1))
        elif pc in ("todas", "Todas"):
            niveis[3].append(l)
        elif pc in ("?", ""):
            niveis[4].append(l)
        elif pc == oposto:
            niveis[5].append(l)
    for n in (1, 2, 3, 4, 5):
        ls = niveis.get(n)
        if not ls:
            continue
        if n >= 4:
            ls = [l for l in ls if legivel(l, cor, cfg, estrito=True if n == 5 else "mediana")
                  and (not visual or visual.get(l["caminho"], 1.0) >= 0.45)]
            if not ls:
                continue
        else:
            # feita para este tom, mas a tinta medida some no tecido? usa, mas manda revisar
            boas = [l for l in ls if legivel(l, cor, cfg)]
            if not boas:
                ls = sorted(ls, key=lambda l: chave_ordem(l, cfg))
                marcada = "arte única para todas as cores" if n == 3 else f"a arte está marcada para camisa {alvo}"
                return ls[0], 4, f"{marcada}, mas a tinta medida quase não aparece na {cor} — conferir"
            ls = boas
        ls = sorted(ls, key=lambda l: (l.get("_outra_cor", 0), chave_ordem(l, cfg)))
        if visual:
            # comparação com a foto atual vence a ordem quando a diferença é clara
            melhor = max(ls, key=lambda l: visual.get(l["caminho"], -1))
            if visual.get(melhor["caminho"], -1) - visual.get(ls[0]["caminho"], -1) > 0.1:
                ls = [melhor] + [l for l in ls if l is not melhor]
        obs = {1: "", 2: "", 3: "arte única para todas as cores",
               4: "não sei se a arte é para camisa clara ou escura — conferir",
               5: f"só existe a versão para camisa {oposto}; parece legível na {cor}, mas confira"}[n]
        return ls[0], n, obs
    ilegiveis = niveis.get(5, []) + niveis.get(4, [])
    if ilegiveis:
        return None, 0, (f"só existe a versão para camisa {oposto} (tinta {'escura' if oposto == 'clara' else 'clara'}), "
                         f"que some na {cor} ou não bate com a foto atual: falta a versão para camisa {alvo}")
    return None, 0, ""


def geometria_padrao_arte(lado: str, aspecto: Optional[float], cfg: dict, produto: Optional[Produto] = None
                          ) -> Tuple[float, float, float]:
    """Posição padrão (medida nas fotos JA FOI) ajustada à proporção da arte."""
    from estampar import geometria_padrao
    (w, t, cx), _ = geometria_padrao(lado, cfg, produto)
    if lado == "costas" and aspecto:
        g = cfg["geometria_padrao"]["costas"]
        larga, a_l, a_a = float(g.get("largura_rel_larga", w)), float(g.get("aspecto_largo", 0.9)), float(
            g.get("aspecto_alto", 1.3))
        if aspecto <= a_l:
            w = larga
        elif aspecto < a_a:
            w = larga + (w - larga) * (aspecto - a_l) / (a_a - a_l)
        hmax, razao = float(g.get("altura_rel_max", 0.545)), float(g.get("razao_torso", 0.59))
        w = min(w, hmax / (aspecto * razao))
    return round(w, 4), round(t, 4), round(cx, 4)


def _mediana(gs: List[Tuple[float, float, float]]) -> Tuple[float, float, float]:
    return tuple(round(statistics.median(v), 4) for v in zip(*gs))


def medidas_analise(analise: List[dict]) -> Tuple[Dict[tuple, tuple], Dict[tuple, str]]:
    """(handle, lado) -> geometria mediana; (handle, lado) -> 'sim'|'nao' (a foto atual mostra estampa?)."""
    geos: Dict[tuple, list] = defaultdict(list)
    tem: Dict[tuple, set] = defaultdict(set)
    for l in analise:
        h, lado = l.get("handle"), l.get("lado")
        if not h or lado not in ("frente", "costas") or str(l.get("observacao", "")).startswith("erro"):
            continue
        tem[(h, lado)].add(l.get("tem_estampa") or "nao")
        if l.get("tem_estampa") == "sim":
            try:
                geos[(h, lado)].append((float(l["largura_rel"]), float(l["topo_rel"]),
                                        float(l.get("centro_x_rel") or 0)))
            except (KeyError, ValueError):
                pass
    medidas = {k: _mediana(v) for k, v in geos.items() if v}
    estado = {k: ("sim" if "sim" in v else "nao") for k, v in tem.items()}
    return medidas, estado


def montar_mapa(produtos: List[Produto], inventario: List[dict], analise: List[dict], cfg: dict,
                manuais: Optional[List[dict]] = None, existe: Callable[[str], bool] = lambda c: True,
                visual: Optional[Dict[tuple, Dict[str, float]]] = None,
                tintas: Optional[Dict[tuple, Dict[str, dict]]] = None) -> List[dict]:
    """Uma linha por camiseta x cor x lado. Linhas manuais (origem=manual) são mantidas como estão."""
    visual = visual or {}
    tintas = tintas or {}
    por_produto: Dict[str, List[dict]] = defaultdict(list)
    for l in inventario:
        if not (eh_arte(l) and l.get("versao_preferida") != "nao" and existe(l["caminho"])):
            continue
        if l.get("produto") not in ("", "?") and l.get("lado") in ("frente", "costas"):
            por_produto[chave_titulo(l["produto"])].append(l)
        for extra in reusos(l):
            por_produto[chave_titulo(extra["produto"])].append(extra)
    medidas, estado = medidas_analise(analise)
    man = {}
    for m in manuais or []:
        man[(m.get("handle"), m.get("cor", ""), m.get("lado"))] = m
    cmin = float(cfg["casar"].get("confianca_minima", 0.6))
    out: List[dict] = []
    for p in produtos:
        arts = por_produto.get(chave_titulo(p.titulo), [])
        desc = p.lados_descricao
        for cor in p.cores:
            for lado in ("costas", "frente"):
                if (p.handle, cor, lado) in man:
                    out.append(dict(man[(p.handle, cor, lado)]))
                    continue
                if (p.handle, "", lado) in man:
                    continue  # linha manual valendo para todas as cores
                row = {k: "" for k in COLUNAS_MAPA_CASAR}
                row.update({"handle": p.handle, "NOME": p.nome, "titulo": p.titulo, "cor": cor, "lado": lado})
                obs = []
                c = cor_por_nome(cor, cfg)
                if c is not None and c.especial:
                    obs.append("cor especial (bicolor) sem mockup liso")
                cands = [a for a in arts if a["lado"] == lado]
                foto = estado.get((p.handle, lado))   # 'sim' / 'nao' / None (sem foto analisada)
                esperado = (foto == "sim") or (foto is None and lado in desc) or (
                    foto is None and not desc and lado == "costas")
                vis = visual.get((p.handle, cor, lado))
                arte, nivel, o = escolher_arte(cands, cor, cfg, vis) if cands else (None, 0, "")
                if foto == "nao" and lado == "frente":
                    # a foto atual mostra a frente lisa: segue a loja, mesmo havendo arquivo de frente
                    row.update({"arquivo_estampa": LISO, "origem": "medido", "confianca": "0.9", "revisar": "nao"})
                    if cands:
                        obs.append("há arte de frente nas pastas, mas a foto atual da loja mostra a frente lisa")
                    if lado in desc:
                        obs.append("a descrição cita frente, mas a foto atual não tem estampa na frente")
                    row["observacao"] = "; ".join(obs)
                    out.append(row)
                    continue
                if arte is None:
                    if esperado or o:
                        row.update({"arquivo_estampa": "", "origem": "", "confianca": "0", "revisar": "sim"})
                        obs.append(o or f"falta a estampa {'das costas' if lado == 'costas' else 'da frente'}")
                    else:
                        row.update({"arquivo_estampa": LISO, "confianca": "0.8", "revisar": "nao"})
                    row["observacao"] = "; ".join(obs)
                    out.append(row)
                    continue
                row["arquivo_estampa"] = arte["caminho"]
                row["para_camisa"] = arte.get("cor_especifica") or arte.get("para_camisa", "")
                if row["para_camisa"] in ("?", ""):
                    row["para_camisa"] = "indefinida"
                if (p.handle, lado) in medidas:
                    g, row["origem"] = medidas[(p.handle, lado)], "medido"
                else:
                    asp = _f(arte.get("aspecto_arte")) or None
                    g, row["origem"] = geometria_padrao_arte(lado, asp, cfg, p), "padrao"
                row["largura_rel"], row["topo_rel"], row["centro_x_rel"] = (f"{v:.4f}" for v in g)
                conf = {1: 0.9, 2: 0.85, 3: 0.8, 4: 0.5, 5: 0.45}[nivel]
                if arte.get("origem") == "nome":
                    conf -= 0.2
                if arte.get("origem") == "visual":
                    conf = min(conf, 0.55)
                if arte.get("origem") == "confirmar":
                    conf = min(conf, 0.55)
                    obs.append("arte atribuída a este produto por dedução — confirmar com o dono")
                if arte.get("_reuso"):
                    obs.append(f"mesma arte de {arte['_reuso']} (reaproveitada)")
                s = (vis or {}).get(arte["caminho"])
                if s is not None:
                    conf = round(0.5 * conf + 0.5 * min(1.0, s / 0.75), 3)
                    if s < 0.45:
                        obs.append(f"pouco parecida com a foto atual (nota {s:.2f})")
                if o:
                    obs.append(o)
                dif = (tintas.get((p.handle, cor, lado)) or {}).get(arte["caminho"])
                tinta_ruim = False
                if dif is not None and (dif["dE"] > LIMITE_TINTA_DE or abs(dif["dC"]) > LIMITE_TINTA_DC):
                    desc_dif = (f"tinta {'mais clara' if dif['dL'] > 0 else 'mais escura'} que na foto da loja "
                                f"(ΔL {dif['dL']:+.0f}, saturação ΔC {dif['dC']:+.0f}, ΔE {dif['dE']:.0f})")
                    # tinta de uma cor só e mesma arte (forma parecida com a foto): dá para ajustar a cor
                    if dif["mono"] >= 0.55 and (dif["dE"] <= 45 or (dif.get("nota", 0) >= 0.8 and dif["dE"] <= 60)):
                        row["ajuste_tinta"] = texto_ajuste(dif)
                        obs.append(desc_dif + ": cor da tinta ajustada automaticamente para a da loja "
                                   "(coluna ajuste_tinta; apague para usar a cor original)")
                    else:
                        tinta_ruim = True
                        obs.append(desc_dif + ": parece outra versão da arte — conferir qual é a oficial")
                if arte.get("qualidade") not in QUALIDADE_OK:
                    obs.append(f"arte com problema: {arte['qualidade']}")
                    conf = min(conf, 0.55)
                if not esperado:
                    obs.append(f"a descrição não cita estampa {'nas costas' if lado == 'costas' else 'na frente'}")
                    conf = min(conf, 0.55)
                if len({a['caminho'] for a in cands}) > 1 and nivel <= 3:
                    outras = [a for a in cands if a is not arte and a.get("escolhida") == "sim"
                              and a.get("para_camisa") == arte.get("para_camisa")]
                    if outras:
                        obs.append(f"há {len(outras)} outra(s) arte(s) diferentes para este lado")
                if tinta_ruim:
                    conf = min(conf, 0.55)
                row["confianca"] = f"{conf:.2f}"
                row["revisar"] = "sim" if conf < cmin or nivel >= 4 or arte.get("qualidade") not in QUALIDADE_OK \
                    else "nao"
                row["observacao"] = "; ".join(obs)
                out.append(row)
    # linhas manuais de produtos/cores que não estão no CSV continuam no arquivo
    chaves = {(r["handle"], r["cor"], r["lado"]) for r in out}
    for k, m in man.items():
        if k not in chaves:
            out.append(dict(m))
    return out


# Diferença de tinta (Lab) entre a arte escolhida e a foto atual que manda revisar / ajustar.
LIMITE_TINTA_DE = 14.0
LIMITE_TINTA_DC = 18.0


def reusos(l: dict) -> List[dict]:
    """Coluna usar_tambem do inventário: a mesma arte serve para outro produto/lado.

    Formato: "PRODUTO T-SHIRT:lado:para_camisa" separados por ';' (para_camisa: clara|escura|todas).
    """
    out = []
    for item in str(l.get("usar_tambem", "") or "").split(";"):
        partes = [x.strip() for x in item.split(":")]
        if len(partes) < 2 or not partes[0] or partes[1] not in ("frente", "costas"):
            continue
        d = dict(l)
        d.update({"produto": partes[0], "lado": partes[1], "cor_especifica": "",
                  "para_camisa": partes[2] if len(partes) > 2 and partes[2] else l.get("para_camisa", ""),
                  "_reuso": f"{l.get('produto') or '?'} ({l.get('lado')})"})
        out.append(d)
    return out


def ler_manuais(caminho: Path) -> List[dict]:
    """Linhas com origem=manual de um mapa.csv existente (aceita ; ou ,)."""
    if not Path(caminho).exists():
        return []
    import csv
    texto = Path(caminho).read_text(encoding="utf-8-sig")
    if not texto.strip():
        return []
    prim = texto.splitlines()[0]
    sep = ";" if prim.count(";") > prim.count(",") else ","
    out = []
    for l in csv.DictReader(texto.splitlines(), delimiter=sep):
        l = {(k or "").strip(): (v or "").strip() for k, v in l.items()}
        if l.get("origem", "").lower() == "manual" and l.get("handle"):
            d = {k: l.get(k, "") for k in COLUNAS_MAPA_CASAR}
            if d["cor"]:
                from catalogo import CONFIG_PADRAO, normalizar_cor
                d["cor"] = normalizar_cor(d["cor"], CONFIG_PADRAO)[0]
            out.append(d)
    return out


# ---------------------------------------------------------------------------
# Duplicatas
# ---------------------------------------------------------------------------

def _eh_copia(caminho: str) -> int:
    n = sem_acentos(caminho.split("/")[-1]).lower()
    return 1 if ("copia" in n or "copy" in n) else 0


def mesma_finalidade(a: dict, b: dict) -> bool:
    """Versões para camisa clara e para camisa escura nunca são duplicatas uma da outra."""
    pa, pb = a.get("para_camisa", ""), b.get("para_camisa", "")
    if pa in ("clara", "escura") and pb in ("clara", "escura") and pa != pb:
        return False
    ca, cb = a.get("cor_especifica", ""), b.get("cor_especifica", "")
    return not (ca and cb and ca != cb)


def marcar_duplicatas(linhas: List[dict], cfg: dict) -> List[Tuple[str, str, str]]:
    """Exatas (sha1) e visuais (hash) entre artes do mesmo produto. Mantém a melhor (chave_ordem).

    Retorna [(removido, mantido, tipo)] e marca versao_preferida=nao + duplicata_de nos removidos.
    """
    removidos = []
    por_sha: Dict[str, List[dict]] = defaultdict(list)
    for l in linhas:
        if l.get("sha1"):
            por_sha[l["sha1"]].append(l)
    for ls in por_sha.values():
        if len(ls) > 1:
            ls.sort(key=lambda l: (0 if eh_arte(l) else 1, _eh_copia(l["caminho"]))
                    + chave_ordem(dict(l, versao_preferida="", qualidade="ok"), cfg))
            for l in ls[1:]:
                for k in ("produto", "lado", "para_camisa", "cor_especifica"):
                    if not ls[0].get(k) and l.get(k):
                        ls[0][k] = l[k]
            for l in ls[1:]:
                if l.get("duplicata_de") != ls[0]["caminho"] or l.get("versao_preferida") != "nao":
                    l["duplicata_de"] = ls[0]["caminho"]
                    l["versao_preferida"] = "nao"
                removidos.append((l["caminho"], ls[0]["caminho"], "exata"))
    dist = int(cfg["casar"].get("hash_visual_distancia", 6))
    por_prod: Dict[tuple, List[dict]] = defaultdict(list)
    for l in linhas:
        if eh_arte(l) and l.get("hash_visual") and l.get("versao_preferida") != "nao" and l.get("produto") not in ("", "?"):
            por_prod[(l["produto"], l["lado"])].append(l)
    for ls in por_prod.values():
        ls.sort(key=lambda l: chave_ordem(l, cfg))
        mantidos: List[dict] = []
        for l in ls:
            dup = next((m for m in mantidos if hamming(m["hash_visual"], l["hash_visual"]) <= dist
                        and mesma_finalidade(m, l)
                        and abs(math.log(max(_f(m.get("aspecto_arte"), 1), 1e-3) /
                                         max(_f(l.get("aspecto_arte"), 1), 1e-3))) < 0.08
                        and abs(_f(m.get("tinta_l50"), 50) - _f(l.get("tinta_l50"), 50)) < 20), None)
            if dup is None:
                mantidos.append(l)
            else:
                l["duplicata_de"] = dup["caminho"]
                l["versao_preferida"] = "nao"
                removidos.append((l["caminho"], dup["caminho"], "visual"))
    return removidos


# ---------------------------------------------------------------------------
# revisao.html
# ---------------------------------------------------------------------------

def _rel(destino: Path, alvo: str) -> str:
    try:
        return Path(os.path.relpath(alvo, destino.parent)).as_posix()
    except ValueError:
        return Path(alvo).as_uri()


def escrever_revisao(destino: Path, mapa: List[dict], miniaturas: Dict[tuple, str], fotos: Dict[tuple, str],
                     listas: Dict[str, List[str]], resumo: Dict[str, int]) -> None:
    from relatorios import _pagina
    e = html.escape
    partes = [f"<h1>PALLACIO — revisão das estampas</h1><p class='sub'>Foto atual da loja x arte escolhida, por "
              f"camiseta, cor e lado. Corrija no mapa.csv (coluna arquivo_estampa) e marque origem=manual "
              f"para o programa não mexer mais na linha.</p><div class='cards'>"]
    for k, v in resumo.items():
        partes.append(f"<div class='card'><b>{v}</b>{e(k)}</div>")
    partes.append("</div><input placeholder='Buscar produto...' oninput='filtrar(this.value)'>"
                  "<label style='margin-left:12px'><input type='checkbox' style='width:auto' "
                  "onchange='soProblemas(this.checked)'> só revisar</label>")
    css = ("<style>.prod{background:var(--card);border:1px solid var(--linha);border-radius:10px;padding:10px;"
           "margin:12px 0}.grade{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}"
           ".cel{font-size:12px;overflow-wrap:anywhere}.cel img{width:100%;height:120px;object-fit:contain;border-radius:6px;"
           "background:var(--fundo)}.duo{display:grid;grid-template-columns:1fr 1fr;gap:4px}"
           ".vazio{height:120px;display:flex;align-items:center;justify-content:center;border:1px dashed var(--linha);"
           "border-radius:6px;color:var(--sub)}</style>")
    partes.append(css)
    grupos: Dict[str, List[dict]] = defaultdict(list)
    for r in mapa:
        grupos[r["handle"]].append(r)
    for h, rs in grupos.items():
        grav = "rev" if any(r.get("revisar") == "sim" for r in rs) else "ok"
        partes.append(f"<div class='prod' data-busca='{e((rs[0].get('titulo') or h).lower())}' data-grav='{grav}'>"
                      f"<h2 style='margin:0 0 8px'>{e(rs[0].get('titulo') or h)}</h2><div class='grade'>")
        for r in rs:
            arq = r.get("arquivo_estampa", "")
            conf = _f(r.get("confianca"), 0)
            classe = "ok" if r.get("revisar") != "sim" else ("erro" if not arq else "aviso")
            foto = fotos.get((h, r["cor"], r["lado"]))
            f_html = f"<img src='{e(_rel(destino, foto))}' loading='lazy'>" if foto else "<div class='vazio'>sem foto</div>"
            if arq == LISO:
                a_html = "<div class='vazio'>lado liso</div>"
            elif arq and (arq, r["cor"]) in miniaturas:
                a_html = f"<img src='{e(_rel(destino, miniaturas[(arq, r['cor'])]))}' loading='lazy'>"
            else:
                a_html = "<div class='vazio'>falta</div>" if not arq else "<div class='vazio'>sem prévia</div>"
            partes.append(
                f"<div class='cel'><div class='duo'>{f_html}{a_html}</div><b>{e(r['cor'])} · {e(r['lado'])}</b> "
                f"<span class='tag {classe}'>{'revisar' if r.get('revisar') == 'sim' else 'ok'} {conf:.2f}</span>"
                f"<br><span class='sub'>{e(arq.split('/')[-1] if arq else '—')}</span>"
                f"{'<br>' + e(r['observacao']) if r.get('observacao') else ''}</div>")
        partes.append("</div></div>")
    for titulo, itens in listas.items():
        partes.append(f"<h2>{e(titulo)} ({len(itens)})</h2>")
        if itens:
            partes.append("<ul>" + "".join(f"<li>{e(i)}</li>" for i in itens) + "</ul>")
        else:
            partes.append("<p class='sub'>nenhum</p>")
    destino.write_text(_pagina("PALLACIO — revisão das estampas", "".join(partes)), encoding="utf-8")


# ---------------------------------------------------------------------------
# Comando
# ---------------------------------------------------------------------------

def previas_sobre_tecido(mapa: List[dict], miniaturas: Dict[str, str], pasta: Path, cfg: dict) -> Dict[tuple, str]:
    """(arquivo, cor) -> JPG pequeno da arte sobre a cor do tecido (para enxergar tinta clara na revisão)."""
    out: Dict[tuple, str] = {}
    pasta.mkdir(parents=True, exist_ok=True)
    for r in mapa:
        arq, cor = r.get("arquivo_estampa", ""), r.get("cor", "")
        if (arq, cor) in out or arq not in miniaturas:
            continue
        c = cor_por_nome(cor, cfg)
        rgb = tuple(c.rgb) if c is not None else (200, 200, 200)
        dest = pasta / f"{hashlib.sha1(arq.encode()).hexdigest()[:16]}_{chave_titulo(cor)}.jpg"
        if not dest.exists():
            try:
                with Image.open(miniaturas[arq]) as m:
                    m = m.convert("RGBA")
                    m.thumbnail((240, 240))
                    base = Image.new("RGB", (m.size[0] + 16, m.size[1] + 16), rgb)
                    base.paste(m.convert("RGB"), (8, 8), m.getchannel("A"))
                    base.save(dest, quality=85)
            except Exception:  # noqa: BLE001
                continue
        out[(arq, cor)] = str(dest)
    return out


def _recortes_fotos(analise: List[dict], pasta: Path) -> Dict[tuple, dict]:
    """(handle, cor, lado) -> linha da analise com estampa (a de maior confiança)."""
    out = {}
    for l in analise:
        if l.get("tem_estampa") != "sim" or l.get("lado") not in ("frente", "costas") or not l.get("cor"):
            continue
        k = (l["handle"], l["cor"], l["lado"])
        if k not in out or _f(l.get("cor_confianca")) > _f(out[k].get("cor_confianca")):
            out[k] = l
    return out


def comando(proj, args) -> None:
    import time
    cfg = proj.cfg
    t0 = time.time()
    produtos = ler_catalogo(proj.caminho_csv(getattr(args, "csv", None)), cfg, proj.tipo)
    titulos = {chave_titulo(p.titulo): p.titulo for p in produtos}
    raiz = achar_raiz_arquivos(proj, getattr(args, "arquivos", None))
    inv_path = Path(getattr(args, "inventario", None) or (proj.raiz / "inventario.csv"))
    if not inv_path.exists():
        inv_path = INVENTARIO_PADRAO
    inventario = ler_inventario(inv_path) if inv_path.exists() else []
    print(f"Inventário: {inv_path} ({len(inventario)} arquivos conhecidos)")
    workers = max(1, int(getattr(args, "workers", 4) or 4))
    pasta_cache = proj.pasta("analise", criar=True) / "artes"
    def barra(i, n, txt):
        from pallacio import _barra
        _barra(i, n, txt)
    novos: List[dict] = []
    faltando: List[str] = []
    if raiz is None:
        print("Aviso: não achei a pasta com as artes (CAMISETAS 100%, NOVAS...). Uso só o inventário; "
              "informe a pasta com --arquivos PASTA.")
        existe = lambda c: True  # noqa: E731
    else:
        print(f"Pasta das artes: {raiz}")
        pastas = list(cfg["casar"]["pastas_estampas"]) + list(getattr(args, "estampas", None) or [])
        no_disco = escanear(raiz, pastas)
        conhecidos = {l["caminho"] for l in inventario}
        faltando = sorted(c for c in conhecidos if c not in set(no_disco))
        novos_rel = [c for c in no_disco if c not in conhecidos]
        if novos_rel:
            print(f"{len(novos_rel)} arquivo(s) novo(s) fora do inventário: lendo...")
            from imagem import problema_formato
            legiveis = [raiz / c for c in novos_rel if not problema_formato(Path(c))
                        and Path(c).suffix.lower() not in (".md", ".txt", ".json", ".py", ".html", ".csv")]
            fic, _err = fichas(legiveis, pasta_cache, cfg, workers, barra)
            apelidos = apelidos_de_pasta(inventario)
            for c in novos_rel:
                info = fic.get(str(raiz / c))
                if info is not None:
                    info = dict(info, foto_loja=parece_foto_loja(raiz / c))
                    l = classificar_novo(c, info, titulos, apelidos, cfg)
                    l["sha1"] = sha1_arquivo(raiz / c)
                    l["_miniatura"] = info.get("miniatura", "")
                else:
                    l = classificar_novo(c, None, titulos, apelidos, cfg)
                novos.append(l)
        existe_set = set(no_disco)
        existe = lambda c: c in existe_set  # noqa: E731
    todas = inventario + novos
    duplicadas = marcar_duplicatas(todas, cfg)
    # comparação visual com as fotos atuais
    analise = ler_csv_dicts(proj.arquivo("analise_csv"))
    fotos_rec = _recortes_fotos(analise, proj.pasta("analise"))
    visual: Dict[tuple, Dict[str, float]] = {}
    tintas: Dict[tuple, Dict[str, dict]] = {}
    miniaturas: Dict[str, str] = {}
    fotos_html: Dict[tuple, str] = {}
    pasta_fotos = proj.pasta("analise", criar=True) / "revisao"
    if raiz is not None:
        alvo_fichas = set()
        por_titulo = defaultdict(list)
        for l in todas:
            if eh_arte(l) and l.get("versao_preferida") != "nao" and existe(l["caminho"]):
                por_titulo[chave_titulo(l.get("produto", ""))].append(l)
                for extra in reusos(l):
                    por_titulo[chave_titulo(extra["produto"])].append(extra)
        handles = {p.handle: p for p in produtos}
        for (h, cor, lado) in fotos_rec:
            p = handles.get(h)
            if p:
                alvo_fichas |= {l["caminho"] for l in por_titulo.get(chave_titulo(p.titulo), []) if l["lado"] == lado}
        alvo_fichas |= {l["caminho"] for l in todas if eh_arte(l) and l.get("escolhida") == "sim"
                        and existe(l["caminho"])}
        if not getattr(args, "sem_miniaturas", False):
            alvo_fichas |= {l["caminho"] for l in todas if eh_arte(l) and l.get("versao_preferida") != "nao"
                            and l.get("produto") not in ("", "?") and existe(l["caminho"])}
        if alvo_fichas:
            print(f"Preparando {len(alvo_fichas)} artes (prévia sem fundo; fica guardado para as próximas vezes)...")
        fic, _ = fichas([raiz / c for c in sorted(alvo_fichas)], pasta_cache, cfg, workers, barra)
        for c in alvo_fichas:
            info = fic.get(str(raiz / c))
            if info and info.get("miniatura"):
                miniaturas[c] = info["miniatura"]
        # extremos da tinta (10% / 90%) para o teste de legibilidade: detalhes pequenos (um texto
        # preto numa arte colorida) não aparecem nos quartis do inventário
        for l in todas:
            if l["caminho"] in miniaturas and not l.get("tinta_l10"):
                ext = extremos_tinta(miniaturas[l["caminho"]])
                if ext:
                    l["tinta_l10"], l["tinta_l90"] = ext
        # notas visuais
        mini_img: Dict[str, Image.Image] = {}
        for (h, cor, lado), la in fotos_rec.items():
            p = handles.get(h)
            if p is None:
                continue
            rgb = tuple(int(v) for v in str(la.get("rgb_tecido", "128,128,128")).split(","))
            bbox = tuple(float(la[k]) for k in ("bbox_x0", "bbox_y0", "bbox_x1", "bbox_y1"))
            af = assinatura_foto(la["arquivo"], bbox, rgb)
            if af is None:
                continue
            tf = tinta_foto(la["arquivo"], bbox, rgb)
            dest = pasta_fotos / h / f"{cor}-{lado}.jpg".replace(" ", "_")
            dest.parent.mkdir(parents=True, exist_ok=True)
            rec = af["recorte"].copy()
            rec.thumbnail((300, 300))
            rec.save(dest, quality=85)
            fotos_html[(h, cor, lado)] = str(dest)
            notas = {}
            for l in por_titulo.get(chave_titulo(p.titulo), []):
                if l["lado"] != lado or l["caminho"] not in miniaturas:
                    continue
                if l["caminho"] not in mini_img:
                    with Image.open(miniaturas[l["caminho"]]) as m:
                        mini_img[l["caminho"]] = m.convert("RGBA")
                notas[l["caminho"]] = similaridade(af, assinatura_arte(mini_img[l["caminho"]], rgb))
                dif = comparar_tinta(tf, tinta_arte(mini_img[l["caminho"]], rgb, tf["tamanho"] if tf else None))
                if dif is not None:
                    dif["nota"] = notas[l["caminho"]]
                if dif is not None:
                    tintas.setdefault((h, cor, lado), {})[l["caminho"]] = dif
            visual[(h, cor, lado)] = notas
        # artes novas sem produto: sugere pelo visual
        sem_prod = [l for l in novos if eh_arte(l) and not l.get("produto") and l["caminho"] in miniaturas]
        for l in sem_prod:
            if l["caminho"] not in mini_img:
                with Image.open(miniaturas[l["caminho"]]) as m:
                    mini_img[l["caminho"]] = m.convert("RGBA")
            notas = []
            for (h, cor, lado), la in fotos_rec.items():
                rgb = tuple(int(v) for v in str(la.get("rgb_tecido", "128,128,128")).split(","))
                bbox = tuple(float(la[k]) for k in ("bbox_x0", "bbox_y0", "bbox_x1", "bbox_y1"))
                af = assinatura_foto(la["arquivo"], bbox, rgb)
                if af:
                    notas.append((similaridade(af, assinatura_arte(mini_img[l["caminho"]], rgb)), h, cor, lado))
            notas.sort(reverse=True)
            if notas and notas[0][0] >= 0.6:
                outros = [n for n in notas if n[1] != notas[0][1]]
                if not outros or notas[0][0] - outros[0][0] > 0.08:
                    p = handles[notas[0][1]]
                    l.update({"produto": p.titulo, "lado": notas[0][3], "origem": "visual",
                              "para_camisa": "clara" if tom_da_cor(notas[0][2], cfg) == "claro" else "escura"})
                    l["observacao"] = f"produto deduzido pela semelhança com a foto atual (nota {notas[0][0]:.2f})"
    marcar_escolhidas(todas, cfg)
    mapa_path = proj.arquivo("mapa_csv")
    manuais = ler_manuais(mapa_path)
    mapa = montar_mapa(produtos, todas, analise, cfg, manuais, existe, visual, tintas)
    from catalogo import escrever_csv_dicts
    if mapa_path.exists():
        import shutil
        shutil.copy2(mapa_path, mapa_path.with_suffix(".anterior.csv"))
    escrever_csv_dicts(mapa_path, COLUNAS_MAPA_CASAR, mapa)
    if novos:
        escrever_csv_dicts(proj.raiz / "inventario_novos.csv", COLUNAS_INVENTARIO, novos)
    # listas de pendências
    usados = {r["arquivo_estampa"] for r in mapa}
    orfas = sorted(l["caminho"] for l in todas if eh_arte(l) and l.get("versao_preferida") != "nao"
                   and l["caminho"] not in usados and existe(l["caminho"]))
    sem_produto = sorted(f"{l['caminho']} — {l.get('produto_sugerido') or 'produto desconhecido'}"
                         for l in todas if eh_arte(l) and l.get("produto") in ("", "?"))
    nao_suportados = sorted(f"{l['caminho']} — {l['observacao']}" for l in todas
                            if l.get("tipo") in ("nao_suportado", "ilegivel"))
    nao_artes = sorted(f"{l['caminho']} ({l['tipo']})" for l in todas
                       if l.get("tipo") in ("foto_loja", "mockup_outro", "etiqueta", "outro"))
    faltas = sorted(f"{r['titulo']} — {r['cor']} — {r['lado']}: {r['observacao']}" for r in mapa
                    if not r.get("arquivo_estampa"))
    listas = {
        "Faltam artes": faltas,
        "Artes sem produto no CSV (ou produto desconhecido)": sem_produto,
        "Artes não usadas no mapa (alternativas / sobras)": orfas,
        "Duplicatas ignoradas": [f"{a} = {b} ({t})" for a, b, t in duplicadas],
        "Formatos que não abrem": nao_suportados,
        "Arquivos que não são estampa (ignorados)": nao_artes,
        "No inventário mas não encontrados na pasta": faltando,
    }
    resumo = {
        "linhas no mapa": len(mapa),
        "com arte": sum(1 for r in mapa if r["arquivo_estampa"] not in ("", LISO)),
        "lado liso": sum(1 for r in mapa if r["arquivo_estampa"] == LISO),
        "faltando": len(faltas),
        "para revisar": sum(1 for r in mapa if r.get("revisar") == "sim"),
        "manuais mantidas": len(manuais),
    }
    previas = previas_sobre_tecido(mapa, miniaturas, pasta_fotos / "_artes", cfg)
    escrever_revisao(proj.arquivo("revisao_html"), mapa, previas, fotos_html, listas, resumo)
    print(f"Pronto em {time.time() - t0:.0f}s. mapa.csv: {resumo['linhas no mapa']} linhas "
          f"({resumo['com arte']} com arte, {resumo['lado liso']} lisas, {resumo['faltando']} faltando, "
          f"{resumo['para revisar']} para revisar; {resumo['manuais mantidas']} manuais mantidas).")
    if novos:
        print(f"Arquivos novos classificados: inventario_novos.csv ({len(novos)})")
    print(f"Abra para conferir: {proj.arquivo('revisao_html')}")
