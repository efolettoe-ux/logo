"""Imagens: abrir qualquer formato, separar a camiseta do fundo, achar o tronco e a estampa.

Só Pillow + numpy. Formatos extras (PSD, PDF/AI, SVG, HEIC) usam bibliotecas opcionais se instaladas.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image, ImageOps

from catalogo import ErroUsuario, tabela_cores

Image.MAX_IMAGE_PIXELS = 200_000_000  # mockups grandes são normais


class ErroImagem(ErroUsuario):
    pass


# ---------------------------------------------------------------------------
# Abrir e normalizar
# ---------------------------------------------------------------------------

EXT_NATIVAS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif"}
EXT_PSD = {".psd", ".psb"}
EXT_PDF = {".pdf", ".ai"}
EXT_SVG = {".svg"}
EXT_HEIC = {".heic", ".heif"}
EXT_IMAGEM = EXT_NATIVAS | EXT_PSD | EXT_PDF | EXT_SVG | EXT_HEIC


def problema_formato(caminho: Path) -> Optional[str]:
    """None se dá para abrir; senão, a instrução em português para o usuário."""
    ext = Path(caminho).suffix.lower()
    if ext in EXT_NATIVAS:
        return None
    if ext in EXT_PSD:
        try:
            import psd_tools  # noqa: F401
            return None
        except ImportError:
            return "arquivo PSD: instale o leitor (pip3 install psd-tools) ou exporte como PNG no Photoshop"
    if ext in EXT_PDF:
        try:
            import fitz  # noqa: F401
            return None
        except ImportError:
            return "arquivo PDF/AI: instale o leitor (pip3 install pymupdf) ou exporte como PNG transparente"
    if ext in EXT_SVG:
        try:
            import cairosvg  # noqa: F401
            return None
        except (ImportError, OSError):
            return "arquivo SVG: instale o leitor (pip3 install cairosvg) ou exporte como PNG transparente"
    if ext in EXT_HEIC:
        try:
            import pillow_heif  # noqa: F401
            return None
        except ImportError:
            return "foto HEIC do iPhone: abra no Pré-Visualização e use Arquivo > Exportar > PNG"
    return f"formato {ext or 'sem extensão'} não suportado: exporte como PNG (de preferência com fundo transparente)"


def _abrir_bruto(caminho: Path) -> Image.Image:
    ext = caminho.suffix.lower()
    msg = problema_formato(caminho)
    if msg:
        raise ErroImagem(f"{caminho.name}: {msg}")
    if ext in EXT_PSD:
        from psd_tools import PSDImage
        return PSDImage.open(str(caminho)).composite()
    if ext in EXT_PDF:
        import fitz
        doc = fitz.open(str(caminho))
        pix = doc[0].get_pixmap(dpi=300, alpha=True)
        return Image.frombytes("RGBA" if pix.alpha else "RGB", (pix.width, pix.height), pix.samples)
    if ext in EXT_SVG:
        import cairosvg
        png = cairosvg.svg2png(url=str(caminho), output_width=2400)
        return Image.open(io.BytesIO(png))
    if ext in EXT_HEIC:
        import pillow_heif
        pillow_heif.register_heif_opener()
    im = Image.open(caminho)
    im.load()
    return im


def _para_8bits(im: Image.Image) -> Image.Image:
    """Converte modos exóticos (16 bits, float, paleta, cinza, CMYK...) para RGB/RGBA 8 bits."""
    if im.mode in ("I;16", "I;16B", "I;16L", "I", "F"):
        a = np.asarray(im).astype(np.float64)
        mx = a.max() if a.size else 1
        a = a / (65535.0 if mx > 255 else 255.0) * 255.0
        im = Image.fromarray(np.clip(a + 0.5, 0, 255).astype(np.uint8), "L")
    if im.mode == "P":
        im = im.convert("RGBA" if "transparency" in im.info else "RGB")
    if im.mode in ("1", "L"):
        im = im.convert("RGB")
    elif im.mode in ("LA", "La", "PA", "RGBa"):
        im = im.convert("RGBA")
    elif im.mode not in ("RGB", "RGBA", "CMYK"):
        im = im.convert("RGBA" if "A" in im.mode else "RGB")
    return im


def _para_srgb(im: Image.Image, icc: Optional[bytes]) -> Image.Image:
    alpha = im.getchannel("A") if im.mode == "RGBA" else None
    base = im.convert("RGB") if im.mode == "RGBA" else im
    if icc:
        try:
            from PIL import ImageCms
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            dst = ImageCms.createProfile("sRGB")
            base = ImageCms.profileToProfile(base, src, dst, outputMode="RGB")
        except Exception:
            base = base.convert("RGB")  # perfil quebrado: segue sem ele
    elif base.mode != "RGB":
        base = base.convert("RGB")
    if alpha is not None:
        base = base.copy()
        base.putalpha(alpha)
    return base


def carregar_imagem(caminho, manter_alpha: bool = True) -> Image.Image:
    """Abre qualquer imagem suportada e devolve RGB ou RGBA (8 bits, sRGB, já girada pelo EXIF).

    RGBA só se a imagem tiver transparência de verdade (e manter_alpha=True).
    """
    caminho = Path(caminho)
    if not caminho.exists():
        raise ErroImagem(f"Arquivo não encontrado: {caminho}")
    try:
        im = _abrir_bruto(caminho)
        if getattr(im, "n_frames", 1) > 1:
            im.seek(0)
        icc = im.info.get("icc_profile")
        im = ImageOps.exif_transpose(im)
        im = _para_8bits(im)
        im = _para_srgb(im, icc)
    except ErroImagem:
        raise
    except Exception as e:  # arquivo corrompido, formato estranho...
        raise ErroImagem(f"Não consegui abrir {caminho.name} ({type(e).__name__}: {e}). Exporte de novo como PNG.")
    if im.mode == "RGBA":
        a = np.asarray(im.getchannel("A"))
        if a.min() >= 255 or not manter_alpha:
            im = im.convert("RGB")
    return im


def tem_transparencia(im: Image.Image) -> bool:
    return im.mode == "RGBA" and int(np.asarray(im.getchannel("A")).min()) < 250


def recortar_alpha(im: Image.Image, limiar: int = 24) -> Image.Image:
    """Corta as bordas transparentes da estampa (a medida da estampa é sempre a da parte visível)."""
    if im.mode != "RGBA":
        return im
    a = np.asarray(im.getchannel("A"))
    m = a > limiar
    if not m.any():
        return im

    def faixa(perfil):
        # ignora pontinhos soltos nas bordas (resto de fundo): corta as pontas com < 0,15% da tinta
        c = np.cumsum(perfil, dtype=np.float64)
        tot = c[-1]
        i0 = int(np.searchsorted(c, tot * 0.0015))
        i1 = int(np.searchsorted(c, tot * 0.9985))
        return i0, min(len(perfil) - 1, i1)

    x0, x1 = faixa(m.sum(axis=0))
    y0, y1 = faixa(m.sum(axis=1))
    return im.crop((x0, y0, x1 + 1, y1 + 1))


# ---------------------------------------------------------------------------
# Utilitários numpy (desfoque, morfologia, flood fill, componentes)
# ---------------------------------------------------------------------------

def _caixa_1d(a: np.ndarray, r: int, eixo: int) -> np.ndarray:
    """Média móvel de raio r ao longo do eixo (bordas replicadas)."""
    if r <= 0:
        return a
    pad = [(0, 0)] * a.ndim
    pad[eixo] = (r + 1, r)
    c = np.cumsum(np.pad(a, pad, mode="edge"), axis=eixo, dtype=np.float64)
    n = a.shape[eixo]
    sl_hi = [slice(None)] * a.ndim
    sl_lo = [slice(None)] * a.ndim
    sl_hi[eixo] = slice(2 * r + 1, 2 * r + 1 + n)
    sl_lo[eixo] = slice(0, n)
    return ((c[tuple(sl_hi)] - c[tuple(sl_lo)]) / (2 * r + 1)).astype(np.float32)


def desfocar(a: np.ndarray, sigma: float) -> np.ndarray:
    """Desfoque quase-gaussiano (3 passadas de caixa) em 2D ou HxWxC."""
    a = a.astype(np.float32, copy=False)
    if sigma < 0.3:
        return a
    if sigma < 1.2:
        # desfoque pequeno: gaussiana de verdade (as caixas borrariam demais, ~1.4 px no mínimo)
        r = 2 if sigma < 0.8 else 3
        k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2).astype(np.float32)
        k /= k.sum()
        out = a
        for eixo in (0, 1):
            pad = [(0, 0)] * a.ndim
            pad[eixo] = (r, r)
            p = np.pad(out, pad, mode="edge")
            acc = np.zeros_like(out)
            n = out.shape[eixo]
            for i, kv in enumerate(k):
                sl = [slice(None)] * a.ndim
                sl[eixo] = slice(i, i + n)
                acc += kv * p[tuple(sl)]
            out = acc
        return out
    # raio da caixa para 3 passadas aproximarem a gaussiana
    r = max(1, int(round((np.sqrt(4.0 * sigma * sigma + 1.0) - 1.0) / 2.0)))
    out = a
    for _ in range(3):
        out = _caixa_1d(out, r, 0)
        out = _caixa_1d(out, r, 1)
    return out


def _soma_janela(m: np.ndarray, r: int) -> np.ndarray:
    a = m.astype(np.int32)
    for eixo in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[eixo] = (r + 1, r)
        c = np.cumsum(np.pad(a, pad), axis=eixo)
        n = a.shape[eixo]
        hi = [slice(None)] * 2
        lo = [slice(None)] * 2
        hi[eixo] = slice(2 * r + 1, 2 * r + 1 + n)
        lo[eixo] = slice(0, n)
        a = c[tuple(hi)] - c[tuple(lo)]
    return a


def dilatar(m: np.ndarray, r: int) -> np.ndarray:
    return m if r <= 0 else _soma_janela(m, r) > 0


def erodir(m: np.ndarray, r: int) -> np.ndarray:
    return m if r <= 0 else _soma_janela(~m, r) == 0


def propagar(semente: np.ndarray, permitido: np.ndarray, max_voltas: int = 200) -> np.ndarray:
    """Flood fill: tudo de 'permitido' conectado (4-viz.) a alguma semente. Varre linhas e colunas inteiras."""
    perm = permitido.astype(bool)
    atual = semente.astype(bool) & perm
    for _ in range(max_voltas):
        antes = int(atual.sum())
        for transp in (False, True):
            P = perm.T if transp else perm
            S = atual.T if transp else atual
            h, w = P.shape
            inicio = P & ~np.pad(P, ((0, 0), (1, 0)))[:, :w]
            ids = np.cumsum(inicio.ravel()).reshape(h, w) * P
            tocado = np.zeros(int(ids.max()) + 1, dtype=bool)
            tocado[ids[S]] = True
            tocado[0] = False
            novo = tocado[ids]
            atual = novo.T if transp else novo
        if int(atual.sum()) == antes:
            break
    return atual


@dataclass
class Componentes:
    n: int
    area: np.ndarray        # (n,)
    bbox: np.ndarray        # (n,4) x0,y0,x1,y1 (x1/y1 exclusivos)
    rotulos: np.ndarray     # HxW int32, 0 = fundo


def rotular(m: np.ndarray) -> Componentes:
    """Componentes conectados (8-viz.) por union-find de trechos de linha."""
    h, w = m.shape
    d = np.diff(np.pad(m.astype(np.int8), ((0, 0), (1, 1))), axis=1)
    ys, xs0 = np.nonzero(d == 1)
    _, xs1 = np.nonzero(d == -1)
    n = len(ys)
    if n == 0:
        return Componentes(0, np.zeros(0), np.zeros((0, 4), int), np.zeros((h, w), np.int32))
    pai = np.arange(n)

    def raiz(i):
        while pai[i] != i:
            pai[i] = pai[pai[i]]
            i = pai[i]
        return i

    linha_ini = np.searchsorted(ys, np.arange(h + 1))
    for y in range(1, h):
        a0, a1 = linha_ini[y - 1], linha_ini[y]
        b0, b1 = linha_ini[y], linha_ini[y + 1]
        i, j = a0, b0
        while i < a1 and j < b1:
            if xs0[j] <= xs1[i] and xs0[i] <= xs1[j]:  # sobreposição com diagonal
                ri, rj = raiz(i), raiz(j)
                if ri != rj:
                    pai[max(ri, rj)] = min(ri, rj)
            if xs1[i] < xs1[j]:
                i += 1
            else:
                j += 1
    raizes = np.array([raiz(i) for i in range(n)])
    unicas, rot = np.unique(raizes, return_inverse=True)
    k = len(unicas)
    comp = xs1 - xs0
    area = np.bincount(rot, weights=comp, minlength=k)
    bbox = np.zeros((k, 4), dtype=np.int64)
    bbox[:, 0] = w
    bbox[:, 1] = h
    np.minimum.at(bbox[:, 0], rot, xs0)
    np.minimum.at(bbox[:, 1], rot, ys)
    np.maximum.at(bbox[:, 2], rot, xs1)
    np.maximum.at(bbox[:, 3], rot, ys + 1)
    rotulos = np.zeros(h * w, dtype=np.int32)
    idx = np.repeat(ys * w + xs0 - np.cumsum(np.r_[0, comp[:-1]]), comp) + np.arange(int(comp.sum()))
    rotulos[idx] = np.repeat(rot + 1, comp)
    return Componentes(k, area, bbox, rotulos.reshape(h, w))


def srgb_para_linear(a: np.ndarray) -> np.ndarray:
    a = a.astype(np.float32, copy=False)
    return np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4).astype(np.float32)


def linear_para_srgb(a: np.ndarray) -> np.ndarray:
    a = np.clip(a, 0.0, 1.0)
    return np.where(a <= 0.0031308, a * 12.92, 1.055 * np.power(a, 1 / 2.4) - 0.055).astype(np.float32)


def rgb_para_lab(rgb: np.ndarray) -> np.ndarray:
    """rgb uint8 (...,3) ou float 0-1 -> Lab (D65)."""
    a = rgb.astype(np.float32)
    if rgb.dtype == np.uint8 or a.max() > 1.5:
        a = a / 255.0
    lin = srgb_para_linear(a)
    M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]], np.float32)
    xyz = lin @ M.T
    xyz = xyz / np.array([0.95047, 1.0, 1.08883], np.float32)
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    L = 116 * f[..., 1] - 16
    A = 500 * (f[..., 0] - f[..., 1])
    B = 200 * (f[..., 1] - f[..., 2])
    return np.stack([L, A, B], axis=-1).astype(np.float32)


def _reduzir(im: Image.Image, lado_max: int) -> Tuple[Image.Image, float]:
    w, h = im.size
    s = min(1.0, lado_max / float(max(w, h)))
    if s >= 1.0:
        return im, 1.0
    return im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.BILINEAR if s > 0.5 else Image.BOX), s


# ---------------------------------------------------------------------------
# Segmentação da peça e tronco
# ---------------------------------------------------------------------------

@dataclass
class Torso:
    """Medidas do tronco em pixels da imagem original.

    topo = linha da gola (ponto mais alto da peça perto do centro); base = barra.
    x0/x1 = laterais do corpo (sem mangas). A geometria da estampa é relativa a isso.
    """
    x0: float
    x1: float
    topo: float
    base: float
    axila: float
    largura_img: int
    altura_img: int

    @property
    def largura(self) -> float:
        return self.x1 - self.x0

    @property
    def altura(self) -> float:
        return self.base - self.topo

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2.0

    def escalar(self, s: float) -> "Torso":
        return Torso(self.x0 * s, self.x1 * s, self.topo * s, self.base * s, self.axila * s,
                     round(self.largura_img * s), round(self.altura_img * s))

    def para_relativo(self) -> dict:
        """Formato do areas.json (frações da largura/altura da imagem)."""
        W, H = float(self.largura_img), float(self.altura_img)
        return {"x0": round(self.x0 / W, 5), "x1": round(self.x1 / W, 5), "topo": round(self.topo / H, 5),
                "base": round(self.base / H, 5), "axila": round(self.axila / H, 5)}

    @staticmethod
    def de_relativo(d: dict, W: int, H: int) -> "Torso":
        ax = d.get("axila", d["topo"] + 0.25 * (d["base"] - d["topo"]))
        return Torso(d["x0"] * W, d["x1"] * W, d["topo"] * H, d["base"] * H, ax * H, W, H)


@dataclass
class Segmentacao:
    mascara: np.ndarray   # bool, na escala reduzida
    escala: float         # reduzida / original
    rgb: np.ndarray       # uint8 reduzida
    fundo_rgb: Tuple[int, int, int]
    transparente: bool


def segmentar_peca(im: Image.Image, cfg: dict) -> Segmentacao:
    """Separa a peça do fundo liso (ou usa a transparência do PNG). Trabalha em resolução reduzida."""
    acfg = cfg["analise"]
    peq, s = _reduzir(im, int(acfg.get("lado_max_segmentacao", 600)))
    if peq.mode == "RGBA" and tem_transparencia(peq):
        a = np.asarray(peq.getchannel("A"))
        rgb = np.asarray(peq.convert("RGB"))
        m = a > 128
        m = _limpar_mascara(m)
        return Segmentacao(m, s, rgb, (255, 255, 255), True)
    rgb = np.asarray(peq.convert("RGB"))
    peca = _segmentar_fundo_liso(rgb, acfg)
    h, w, _ = rgb.shape
    borda = np.zeros((h, w), bool)
    b = max(2, int(0.006 * max(h, w)))
    borda[:b, :] = borda[-b:, :] = True
    borda[:, :b] = borda[:, -b:] = True
    fr = tuple(int(v) for v in np.median(rgb[borda], axis=0))
    return Segmentacao(peca, s, rgb, fr, False)


def _segmentar_fundo_liso(rgb: np.ndarray, acfg: dict) -> np.ndarray:
    """Fundo liso (com vinheta suave) -> máscara da peça.

    O fundo é tudo que se liga à borda sem atravessar um contorno (gradiente de luminância) nem mudar
    muito de cor. Funciona até com camiseta branca em fundo cinza-claro (diferença de 2-3 níveis):
    o contorno fino da peça vira uma "cerca" que o preenchimento não atravessa.
    """
    h, w, _ = rgb.shape
    lab = rgb_para_lab(desfocar(rgb.astype(np.float32), 1.4))
    borda = np.zeros((h, w), bool)
    b = max(2, int(0.006 * max(h, w)))
    borda[:b, :] = borda[-b:, :] = True
    borda[:, :b] = borda[:, -b:] = True
    fundo = np.median(lab[borda], axis=0)
    dist = np.linalg.norm(lab - fundo, axis=-1)
    spread = float(np.percentile(dist[borda], 95))
    tol = max(float(acfg.get("tolerancia_fundo", 14.0)), 2.5 * spread)
    gy, gx = np.gradient(lab[..., 0])
    grad = np.hypot(gx, gy)
    ruido = float(np.percentile(grad[borda], 99.9))
    melhor = None
    for fator in (2.5, 1.6, 4.0, 7.0):
        lim = float(np.clip(fator * ruido, float(acfg.get("limiar_borda_min", 0.12)), 3.0))
        cerca = dilatar((grad >= lim) | (dist >= tol), 1)
        fundo_m = propagar(borda & ~cerca, ~cerca)
        peca = _limpar_mascara(dilatar(~fundo_m, 1))
        frac = float(peca.mean())
        if 0.03 < frac < 0.85:
            return _refinar_contorno(peca, lab, fundo)
        if melhor is None or abs(frac - 0.3) < abs(float(melhor.mean()) - 0.3):
            melhor = peca
    # último recurso: fundo chapado (ex.: nossas próprias imagens novas, cinza liso 237): só a cor,
    # com tolerância bem justa (camiseta branca fica a ~2-3 unidades do fundo)
    tol_justa = max(1.2, 3.0 * spread)
    if tol_justa < tol:
        cerca = (dist >= tol_justa)
        fundo_m = propagar(borda & ~cerca, ~cerca)
        peca = _limpar_mascara(~fundo_m)
        if 0.03 < float(peca.mean()) < 0.85:
            return _refinar_contorno(peca, lab, fundo)
    return melhor


def _refinar_contorno(peca: np.ndarray, lab: np.ndarray, fundo: np.ndarray) -> np.ndarray:
    """O preenchimento para no meio do degradê do contorno: numa faixa fina na borda da máscara,
    cada pixel vai para o lado (tecido ou fundo) cuja cor está mais perto. Só quando tecido e fundo
    são bem diferentes (camiseta branca em fundo cinza-claro fica como está)."""
    h, w = peca.shape
    r = max(2, int(round(0.008 * max(h, w))))
    miolo = erodir(peca, r + 2)
    if miolo.sum() < 100:
        return peca
    tecido = np.median(lab[miolo], axis=0)
    sep = float(np.linalg.norm(tecido - fundo))
    faixa = peca & ~erodir(peca, r)
    if sep < 12.0:
        # peça clara em fundo claro: a cerca de contorno pega também a sombra suave em volta da peça.
        # A sombra e o contorno são mais escuros que o fundo; o tecido, mais claro. Corta pela luminância.
        sep_cor = float(np.linalg.norm(tecido[1:] - fundo[1:]))
        if sep_cor >= 4.0:
            # ex.: off white (amarelado) x fundo cinza neutro: decide pela cor (a*, b*), não pela luz
            d_t = np.linalg.norm(lab[..., 1:] - tecido[1:], axis=-1)
            d_f = np.linalg.norm(lab[..., 1:] - fundo[1:], axis=-1)
            return _limpar_mascara(peca & ~(faixa & (d_f < d_t)))
        if tecido[0] > fundo[0] + 0.4:
            L = lab[..., 0]
            tirar = faixa & (L < (tecido[0] + fundo[0]) / 2.0)
            return _limpar_mascara(peca & ~tirar)
        return peca
    d_t = np.linalg.norm(lab - tecido, axis=-1)
    d_f = np.linalg.norm(lab - fundo, axis=-1)
    tirar = faixa & (d_f < d_t)
    return _limpar_mascara(peca & ~tirar)


def _limpar_mascara(m: np.ndarray) -> np.ndarray:
    """Abre (tira fiapos), fica com o maior pedaço e preenche buracos."""
    h, w = m.shape
    r = max(1, int(round(0.003 * max(h, w))))
    m = dilatar(erodir(m, r), r)
    comp = rotular(m)
    if comp.n == 0:
        return m
    maior = int(np.argmax(comp.area)) + 1
    m = comp.rotulos == maior
    borda = np.zeros_like(m)
    borda[0, :] = borda[-1, :] = True
    borda[:, 0] = borda[:, -1] = True
    fora = propagar(borda & ~m, ~m)
    return m | ~fora


def medir_torso(mascara: np.ndarray, escala: float = 1.0, tamanho_original: Optional[Tuple[int, int]] = None) -> Torso:
    """Tronco a partir da máscara: largura do corpo sem mangas, gola (topo) e barra (base)."""
    m = mascara
    h, w = m.shape
    linhas = np.nonzero(m.any(axis=1))[0]
    if len(linhas) < 20:
        raise ErroImagem("não encontrei a camiseta na imagem (fundo e peça parecidos demais?)")
    y_top, y_bot = int(linhas[0]), int(linhas[-1])
    alt = y_bot - y_top + 1
    esq = np.where(m.any(axis=1), np.argmax(m, axis=1), -1)
    dirt = np.where(m.any(axis=1), w - 1 - np.argmax(m[:, ::-1], axis=1), -1)
    larg = (dirt - esq + 1).astype(np.float64)
    larg[esq < 0] = 0
    # corpo: faixa de 58% a 85% da altura da peça (abaixo das mangas)
    a, b = y_top + int(0.58 * alt), y_top + int(0.85 * alt)
    faixa = larg[a:b]
    if len(faixa) == 0 or np.median(faixa) <= 0:
        raise ErroImagem("não consegui medir o corpo da camiseta")
    L = float(np.median(faixa))
    cx = float(np.median(((esq + dirt) / 2.0)[a:b]))
    # barra: última linha com largura razoável
    ok = np.nonzero(larg > 0.5 * L)[0]
    base = float(ok[-1] + 1)
    # axila: subindo da faixa do corpo, primeira linha bem mais larga (manga)
    axila = float(y_top + 0.3 * alt)
    for y in range(a, y_top, -1):
        if larg[y] > 1.12 * L:
            axila = float(y + 1)
            break
    # gola: ponto mais alto da peça perto do centro (inclui os lados da gola)
    c0, c1 = int(max(0, cx - 0.35 * L)), int(min(w, cx + 0.35 * L + 1))
    col = m[:, c0:c1]
    tem = col.any(axis=0)
    if not tem.any():
        raise ErroImagem("não encontrei a gola da camiseta")
    topos = np.argmax(col, axis=0)[tem]
    topo = float(np.percentile(topos, 3))
    if L < 0.15 * w or base - topo < 0.25 * h:
        raise ErroImagem("a camiseta ficou pequena demais na imagem ou o fundo não é liso")
    W0, H0 = tamanho_original if tamanho_original else (int(round(w / escala)), int(round(h / escala)))
    k = 1.0 / escala
    return Torso((cx - L / 2) * k, (cx + L / 2) * k, topo * k, base * k, axila * k, W0, H0)


# ---------------------------------------------------------------------------
# Cor do tecido
# ---------------------------------------------------------------------------

def cor_tecido(rgb: np.ndarray, mascara: np.ndarray, torso_red: Torso) -> Tuple[int, int, int]:
    """Cor do tecido = moda robusta (cor mais comum) dentro do corpo, ignorando a estampa."""
    t = torso_red
    y0, y1 = int(t.axila + 0.05 * t.altura), int(t.base - 0.04 * t.altura)
    x0, x1 = int(t.x0 + 0.08 * t.largura), int(t.x1 - 0.08 * t.largura)
    reg = rgb[max(0, y0):max(y0 + 1, y1), max(0, x0):max(x0 + 1, x1)]
    msk = mascara[max(0, y0):max(y0 + 1, y1), max(0, x0):max(x0 + 1, x1)]
    px = reg[msk]
    if len(px) < 50:
        px = rgb[mascara]
    lab = rgb_para_lab(px)
    q = np.floor(lab / np.array([5.0, 4.0, 4.0])).astype(np.int64)
    q -= q.min(axis=0)
    dims = q.max(axis=0) + 1
    chave = (q[:, 0] * dims[1] + q[:, 1]) * dims[2] + q[:, 2]
    moda = np.bincount(chave).argmax()
    centro = lab[chave == moda].mean(axis=0)
    perto = np.linalg.norm(lab - centro, axis=1) < 14
    return tuple(int(round(v)) for v in np.median(px[perto], axis=0))


@dataclass
class ClassificacaoCor:
    nome: str            # nome da tabela, ou "desconhecida"
    confianca: float     # 0-1
    distancia: float     # ΔE ponderado até a referência escolhida
    segunda: str
    lab: Tuple[float, float, float]


def classificar_cor(rgb: Tuple[int, int, int], cfg: dict) -> ClassificacaoCor:
    """Compara com as cores de referência (Branca x Off White: pesa mais o amarelado b*)."""
    lab = rgb_para_lab(np.array([rgb], np.uint8))[0]
    res = []
    for c in tabela_cores(cfg):
        if c.especial or not c.ativa:
            continue
        ref = rgb_para_lab(np.array([c.rgb], np.uint8))[0]
        d = lab - ref
        dist = float(np.sqrt((0.5 * d[0]) ** 2 + d[1] ** 2 + (1.6 * d[2]) ** 2))
        res.append((dist, c.nome))
    res.sort()
    if not res:
        return ClassificacaoCor("desconhecida", 0.0, 999.0, "", tuple(lab))
    d1, n1 = res[0]
    d2, n2 = res[1] if len(res) > 1 else (d1 * 3 + 30, "")
    margem = (d2 - d1) / max(d2, 1e-6)
    abs_ok = max(0.0, 1.0 - d1 / 40.0)
    conf = round(min(1.0, margem * 1.6) * (0.4 + 0.6 * abs_ok), 3)
    nome = n1 if d1 < 40 else "desconhecida"
    return ClassificacaoCor(nome, conf, round(d1, 2), n2, tuple(float(round(v, 2)) for v in lab))


def medir_gola(rgb: np.ndarray, mascara: np.ndarray, torso_red: Torso, fundo_tecido: Tuple[int, int, int]) -> float:
    """Profundidade do decote no centro, relativa à largura do tronco (frente > costas).

    Desce do topo da gola pelo centro até encontrar o tecido do corpo.
    """
    t = torso_red
    h, w = mascara.shape
    c0 = int(max(0, t.cx - 0.02 * t.largura))
    c1 = int(min(w, t.cx + 0.02 * t.largura + 1))
    y0 = int(t.topo)
    y1 = int(min(h, t.topo + 0.4 * t.largura))
    if y1 <= y0 + 3:
        return 0.0
    faixa = rgb[y0:y1, c0:c1].astype(np.float32)
    mk = mascara[y0:y1, c0:c1]
    lab = rgb_para_lab(faixa)
    ref = rgb_para_lab(np.array([fundo_tecido], np.uint8))[0]
    d = np.linalg.norm((lab - ref) * np.array([0.6, 1, 1], np.float32), axis=-1)
    tecido = ((d < 9) & mk).mean(axis=1) > 0.7
    k = max(2, int(0.012 * t.largura))
    for i in range(len(tecido) - k):
        if tecido[i:i + k].all():
            return round(i / t.largura, 4)
    return round((y1 - y0) / t.largura, 4)


# ---------------------------------------------------------------------------
# Estampa
# ---------------------------------------------------------------------------

@dataclass
class EstampaDetectada:
    bbox: Tuple[int, int, int, int]  # x0,y0,x1,y1 na imagem original (x1/y1 exclusivos)
    area_rel: float                   # área de tinta / área do tronco
    n_partes: int
    partes: List[Tuple[int, int, int, int]] = field(default_factory=list)  # bbox de cada pedaço (original)


def geometria_relativa(bbox: Tuple[float, float, float, float], torso: Torso) -> dict:
    """bbox da estampa -> medidas relativas ao tronco (as mesmas colunas do mapa.csv)."""
    x0, y0, x1, y1 = bbox
    w, h = x1 - x0, y1 - y0
    return {
        "largura_rel": round(w / torso.largura, 4),
        "topo_rel": round((y0 - torso.topo) / torso.altura, 4),
        "centro_x_rel": round(((x0 + x1) / 2.0 - torso.cx) / torso.largura, 4),
        "aspecto": round(h / max(w, 1e-6), 4),
    }


def caixa_da_geometria(torso: Torso, largura_rel: float, topo_rel: float, centro_x_rel: float,
                       aspecto: float) -> Tuple[float, float, float, float]:
    """Inverso de geometria_relativa: (x, y, largura, altura) em pixels no mockup novo."""
    w = largura_rel * torso.largura
    h = w * aspecto
    x = torso.cx + centro_x_rel * torso.largura - w / 2.0
    y = torso.topo + topo_rel * torso.altura
    return x, y, w, h


def detectar_estampa(im: Image.Image, torso: Torso, rgb_tecido: Tuple[int, int, int], cfg: dict,
                     gola_rel: float = 0.0, mascara: Optional[np.ndarray] = None) -> Optional[EstampaDetectada]:
    """Acha a tinta dentro do tronco: pixels que fogem da cor do tecido (compensando dobras)."""
    acfg = cfg["analise"]
    peq, s = _reduzir(im, int(acfg.get("lado_max_estampa", 1200)))
    t = torso.escalar(s)
    W, H = peq.size
    x0 = int(max(0, t.x0 + 0.03 * t.largura))
    x1 = int(min(W, t.x1 - 0.03 * t.largura))
    y0 = int(max(0, t.topo + max(gola_rel * t.largura, 0.03 * t.largura) + 0.012 * t.largura))
    y1 = int(min(H, t.base - 0.04 * t.altura))
    if x1 - x0 < 10 or y1 - y0 < 10:
        return None
    rgb = np.asarray(peq.convert("RGB"))[y0:y1, x0:x1]
    if mascara is not None:
        mk = np.asarray(Image.fromarray((mascara * 255).astype(np.uint8)).resize((W, H), Image.BILINEAR)) > 127
        dentro = erodir(mk, max(2, int(round(float(acfg.get("margem_costura_rel", 0.045)) * t.largura))))[y0:y1, x0:x1]
    else:
        dentro = np.ones(rgb.shape[:2], bool)
    lab = rgb_para_lab(rgb)
    ref = rgb_para_lab(np.array([rgb_tecido], np.uint8))[0]
    pl = float(acfg.get("peso_luminancia", 0.55))
    d0 = np.linalg.norm((lab - ref) * np.array([pl, 1, 1], np.float32), axis=-1)
    lim_min = float(acfg.get("limiar_estampa_min", 13.0))
    # 1a passada: candidatos grosseiros; 2a: luminância local do tecido (tira dobras/sombras)
    cand = dilatar((d0 > lim_min) & dentro, max(1, int(0.006 * t.largura)))
    peso = ((~cand) & dentro).astype(np.float32)
    sig = 0.035 * t.largura
    L_loc = desfocar(lab[..., 0] * peso, sig) / np.maximum(desfocar(peso, sig), 1e-3)
    L_loc = np.where(desfocar(peso, sig) > 0.05, L_loc, ref[0])
    dif = lab - ref
    dif[..., 0] = lab[..., 0] - L_loc
    d = np.linalg.norm(dif * np.array([pl, 1, 1], np.float32), axis=-1)
    livre = ~cand & dentro
    base = d[livre] if livre.sum() > 100 else d[dentro].ravel()
    med = float(np.median(base))
    mad = float(np.median(np.abs(base - med))) * 1.4826
    limiar = max(lim_min, med + 4.0 * mad)
    m = d > limiar
    # limpeza: fecha traços de letras, remove pontinhos
    rc = max(1, int(round(0.004 * t.largura)))
    m = erodir(dilatar(m, rc), rc) & (d > limiar * 0.5) & dentro
    comp = rotular(m)
    borda_util = dentro & ~erodir(dentro, max(3, int(0.04 * t.largura)))
    borda_util[[0, -1], :] = True
    area_torso = t.largura * t.altura
    amin = float(acfg.get("area_min_componente", 0.00025)) * area_torso
    manter = []
    for i in range(comp.n):
        bx0, by0, bx1, by1 = comp.bbox[i]
        if comp.area[i] < amin or (bx1 - bx0) < 3 or (by1 - by0) < 3:
            continue
        # risco comprido e fino encostado na borda do tecido = costura, barra ou dobra
        lw, lh = bx1 - bx0, by1 - by0
        if ((min(lw, lh) < 0.06 * max(lw, lh) and max(lw, lh) > 0.15 * t.largura)
                or min(lw, lh) < 0.03 * t.largura):
            enc = borda_util[by0:by1, bx0:bx1] & (comp.rotulos[by0:by1, bx0:bx1] == i + 1)
            if enc.any():
                continue
        # linha fina na lateral (costura da manga sobre o corpo, perto da axila)
        ccx0 = (bx0 + bx1) / 2.0 + x0
        if lw < 0.03 * t.largura and lh > 2.0 * lw and abs(ccx0 - t.cx) > 0.33 * t.largura:
            continue
        # etiqueta da gola (logo "Pallacio" pequeno logo abaixo da gola, no centro): não é estampa
        ccx = (bx0 + bx1) / 2.0 + x0
        if (abs(ccx - t.cx) < 0.08 * t.largura and by0 + y0 < t.topo + 0.16 * t.largura
                and (bx1 - bx0) < 0.14 * t.largura and (by1 - by0) < 0.12 * t.largura):
            continue
        manter.append(i)
    if not manter:
        return None
    manter = _agrupar_principal(manter, comp, 0.12 * t.largura)
    bb = comp.bbox[manter]
    bx0, by0 = bb[:, 0].min() + x0, bb[:, 1].min() + y0
    bx1, by1 = bb[:, 2].max() + x0, bb[:, 3].max() + y0
    k = 1.0 / s
    area = float(comp.area[manter].sum()) / area_torso
    partes = [tuple(int(round(v * k)) for v in (b[0] + x0, b[1] + y0, b[2] + x0, b[3] + y0)) for b in bb]
    return EstampaDetectada((int(round(bx0 * k)), int(round(by0 * k)), int(round(bx1 * k)), int(round(by1 * k))),
                            round(area, 5), len(manter), partes)


def _agrupar_principal(ids: List[int], comp: "Componentes", folga: float) -> List[int]:
    """Fica com o grupo da maior mancha: junta pedaços próximos (letras, partes do desenho) e descarta
    pontinhos soltos longe (fiapo, sombra de costura). Pedaço grande (>=15% do maior) sempre fica."""
    ids = sorted(ids, key=lambda i: -comp.area[i])
    maior = comp.area[ids[0]]
    grupo = [ids[0]]
    caixa = comp.bbox[ids[0]].astype(float).copy()
    resto = ids[1:]
    mudou = True
    while mudou and resto:
        mudou = False
        for i in list(resto):
            b = comp.bbox[i]
            dx = max(0.0, caixa[0] - b[2], b[0] - caixa[2])
            dy = max(0.0, caixa[1] - b[3], b[1] - caixa[3])
            if comp.area[i] >= 0.15 * maior or max(dx, dy) <= folga:
                grupo.append(i)
                resto.remove(i)
                caixa = np.array([min(caixa[0], b[0]), min(caixa[1], b[1]), max(caixa[2], b[2]), max(caixa[3], b[3])], float)
                mudou = True
    return grupo


# ---------------------------------------------------------------------------
# Análise completa de uma imagem
# ---------------------------------------------------------------------------

@dataclass
class AnaliseImagem:
    largura: int
    altura: int
    torso: Torso
    rgb_tecido: Tuple[int, int, int]
    cor: ClassificacaoCor
    gola_prof_rel: float
    estampa: Optional[EstampaDetectada]
    geometria: Optional[dict]
    recorte: Optional[Image.Image] = field(default=None, repr=False)  # RGB da estampa (+ margem)

    def para_linha(self) -> dict:
        """Campos do analise.csv que vêm da imagem (o resto — handle, arquivo, lado... — quem chama preenche)."""
        t = self.torso
        d = {
            "cor_medida": self.cor.nome, "cor_confianca": self.cor.confianca,
            "rgb_tecido": "%d,%d,%d" % self.rgb_tecido, "gola_prof_rel": self.gola_prof_rel,
            "tem_estampa": "sim" if self.estampa else "nao",
            "torso_x0": round(t.x0, 1), "torso_x1": round(t.x1, 1), "torso_topo": round(t.topo, 1),
            "torso_base": round(t.base, 1), "largura_img": self.largura, "altura_img": self.altura,
        }
        if self.estampa:
            x0, y0, x1, y1 = self.estampa.bbox
            d.update({"bbox_x0": x0, "bbox_y0": y0, "bbox_x1": x1, "bbox_y1": y1})
            d.update(self.geometria or {})
        return d


def preparar_peca(im: Image.Image, cfg: dict, torso_manual: Optional[dict] = None) -> Tuple[Segmentacao, Torso]:
    """Segmenta e mede o tronco (ou usa o tronco marcado no calibrador, em frações da imagem)."""
    seg = segmentar_peca(im, cfg)
    if torso_manual:
        torso = Torso.de_relativo(torso_manual, im.size[0], im.size[1])
    else:
        torso = medir_torso(seg.mascara, seg.escala, im.size)
        if not seg.transparente:
            torso = refinar_largura_torso(im, torso)
    return seg, torso


def _borda_no_perfil(p: np.ndarray) -> Optional[float]:
    """Perfil de luminância de fora (fundo) para dentro (tecido) -> índice do 1º pixel de tecido.

    Nas fotos da loja a peça tem uma sombra suave em volta: uma rampa que escurece do fundo até a
    borda. A borda de verdade é onde a rampa acaba: um degrau forte para baixo (tecido escuro) ou o
    ponto mais baixo antes de a luz voltar a subir (tecido claro, mais claro que a sombra).
    """
    n = len(p)
    if n < 8:
        return None
    fundo = float(np.median(p[:4]))
    saiu = False
    for i in range(1, n):
        d = float(p[i] - p[i - 1])
        if not saiu:
            if p[i] < fundo - 3.0 or d <= -12.0:
                saiu = True
            else:
                continue
        if d <= -12.0:                       # degrau: tecido escuro começa no pixel i
            return float(i)
        if d >= 2.5:                         # a luz volta a subir: tecido claro começa no pixel i
            return float(i)
    return None


def refinar_largura_torso(im: Image.Image, torso: Torso) -> Torso:
    """Mede a largura do tronco na borda nítida do tecido, em resolução cheia, sem a sombra em volta.

    A segmentação (reduzida) inclui a sombra suave ao lado da peça, o que deixava o tronco ~5% largo
    demais nas fotos da loja (e as estampas novas ~5% estreitas). Só ajusta x0/x1; se a medida não
    for confiável (poucas linhas ou mudança grande), mantém o tronco como estava.
    """
    try:
        cinza = np.asarray(im.convert("L"), np.float32)
    except Exception:
        return torso
    H, W = cinza.shape
    L = torso.largura
    y0 = int(torso.axila + 0.35 * max(1.0, torso.base - torso.axila))
    y1 = int(torso.base - 0.08 * torso.altura)
    if y1 - y0 < 10 or L < 20:
        return torso
    fora, dentro = int(round(0.06 * L)) + 3, int(round(0.07 * L)) + 3
    esq, dir_ = [], []
    for y in np.linspace(y0, y1, 41).astype(int):
        faixa = cinza[max(0, y - 2):min(H, y + 3)].mean(axis=0)
        a, b = max(0, int(torso.x0) - fora), min(W, int(torso.x0) + dentro)
        e = _borda_no_perfil(faixa[a:b]) if b - a > 8 else None
        if e is not None:
            esq.append(a + e)
        a, b = max(0, int(torso.x1) - dentro), min(W, int(torso.x1) + fora)
        d = _borda_no_perfil(faixa[a:b][::-1]) if b - a > 8 else None
        if d is not None:
            dir_.append(b - d)
    if len(esq) < 12 or len(dir_) < 12:
        return torso
    x0, x1 = float(np.median(esq)), float(np.median(dir_))
    nova = x1 - x0
    if not (0.85 * L <= nova <= 1.02 * L):
        return torso
    return Torso(x0, x1, torso.topo, torso.base, torso.axila, torso.largura_img, torso.altura_img)


def analisar_imagem(fonte, cfg: dict, margem_recorte: float = 0.06) -> AnaliseImagem:
    """Analisa uma foto atual da loja: tronco, cor do tecido, decote e estampa (posição e tamanho)."""
    im = fonte if isinstance(fonte, Image.Image) else carregar_imagem(fonte)
    seg, torso = preparar_peca(im, cfg)
    t_red = torso.escalar(seg.escala)
    rgb_tec = cor_tecido(seg.rgb, seg.mascara, t_red)
    cor = classificar_cor(rgb_tec, cfg)
    gola = medir_gola(seg.rgb, seg.mascara, t_red, rgb_tec)
    est = detectar_estampa(im, torso, rgb_tec, cfg, gola, seg.mascara)
    geo = geometria_relativa(est.bbox, torso) if est else None
    rec = None
    if est:
        x0, y0, x1, y1 = est.bbox
        mg = margem_recorte * max(x1 - x0, y1 - y0)
        rec = im.convert("RGB").crop((int(max(0, x0 - mg)), int(max(0, y0 - mg)),
                                      int(min(im.size[0], x1 + mg)), int(min(im.size[1], y1 + mg))))
    return AnaliseImagem(im.size[0], im.size[1], torso, rgb_tec, cor, gola, est, geo, rec)


def _fundo_suave(rgb: np.ndarray, borda: np.ndarray) -> np.ndarray:
    """Modelo do fundo: superfície quadrática (por canal, em Lab) ajustada nos pixels da borda.

    Aguenta vinheta/degradê leve das artes geradas por IA (fundo mais escuro nos cantos etc.).
    """
    h, w, _ = rgb.shape
    lab = rgb_para_lab(rgb)
    ys, xs = np.nonzero(borda)
    sel = slice(None, None, max(1, len(ys) // 4000))
    ys, xs = ys[sel], xs[sel]
    def base(yv, xv):
        u, v = xv / float(w) - 0.5, yv / float(h) - 0.5
        return np.stack([np.ones_like(u), u, v, u * u, v * v, u * v], axis=-1)
    A = base(ys.astype(np.float32), xs.astype(np.float32))
    alvo = lab[ys, xs]
    # ajuste robusto: 2 passadas descartando pixels de borda que já são arte
    peso = np.ones(len(ys), bool)
    coef = None
    for _ in range(3):
        coef, *_ = np.linalg.lstsq(A[peso], alvo[peso], rcond=None)
        res = np.linalg.norm(A @ coef - alvo, axis=-1)
        lim = max(3.0, 3.0 * float(np.median(res[peso])))
        peso = res < lim
        if peso.sum() < 20:
            break
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    return (base(yy, xx) @ coef).astype(np.float32), lab, float(np.median(res[peso])) if peso.any() else 99.0


def remover_fundo(im: Image.Image, tolerancia: float = 16.0, buracos_area_max: float = 0.004) -> Tuple[Image.Image, bool]:
    """Arte sem transparência (JPG...): tira o fundo liso (branco, preto ou outra cor, com degradê leve).

    1. modela o fundo a partir da borda (superfície suave);
    2. preenche a partir da borda tudo que é "fundo" (perto do modelo) e conectado à borda;
    3. buracos pequenos fechados da cor exata do fundo (miolo de letras: o, a, e) também saem;
       áreas internas grandes da mesma cor (ex.: um desenho branco numa arte de fundo branco) ficam;
    4. na transição, "color to alpha": alfa = quanto o pixel se afasta do fundo e a cor é
       descontaminada (tira a mistura com o fundo) — sem halo branco/preto na camiseta.
    Retorna (RGBA, removeu?). Se a borda não for lisa, devolve a imagem como está.
    """
    rgb = np.asarray(im.convert("RGB"))
    h, w, _ = rgb.shape
    borda = np.zeros((h, w), bool)
    b = max(1, int(0.004 * max(h, w)))
    borda[:b, :] = borda[-b:, :] = True
    borda[:, :b] = borda[:, -b:] = True
    fundo_lab, lab, ruido = _fundo_suave(rgb, borda)
    dist = np.linalg.norm(lab - fundo_lab, axis=-1)
    if float(np.median(dist[borda])) > tolerancia * 0.6 or float(np.mean(dist[borda] < tolerancia)) < 0.6:
        return im.convert("RGBA"), False  # borda não é lisa: não mexe
    tol = max(tolerancia, 4.0 * ruido)
    fora = propagar(borda & (dist < tol), dist < tol)
    if fora.mean() < 0.02:
        return im.convert("RGBA"), False
    # buracos pequenos (miolo de letras) da cor do fundo
    resto = ~fora & (dist < tol * 0.6)
    if resto.any() and buracos_area_max > 0:
        comp = rotular(resto)
        lim = buracos_area_max * h * w
        for i in range(comp.n):
            if comp.area[i] <= lim:
                x0, y0, x1, y1 = comp.bbox[i]
                fora[y0:y1, x0:x1] |= comp.rotulos[y0:y1, x0:x1] == i + 1
    # alfa: 0 no fundo, 1 na arte; numa faixa estreita em volta do fundo, "color to alpha":
    # cada pixel = mistura da tinta vizinha com o fundo -> alfa = quanto tem de tinta (projeção em RGB linear)
    faixa = dilatar(fora, 2) & ~erodir(fora, 2)
    lin = srgb_para_linear(rgb.astype(np.float32) / 255.0)
    flin = srgb_para_linear(_lab_para_rgb(fundo_lab))
    miolo = ~fora & ~faixa
    peso = desfocar(miolo.astype(np.float32), 2.5)
    tinta = desfocar(lin * miolo[..., None], 2.5) / np.maximum(peso, 1e-4)[..., None]
    sem_vizinho = peso < 1e-3
    tinta[sem_vizinho] = lin[sem_vizinho]
    d_tf = tinta - flin
    proj = ((lin - flin) * d_tf).sum(-1) / np.maximum((d_tf * d_tf).sum(-1), 1e-6)
    alpha = np.ones((h, w), np.float32)
    alpha[fora] = 0.0
    alpha[faixa] = np.clip(proj[faixa], 0.0, 1.0)
    alpha[faixa & sem_vizinho] = np.where(fora[faixa & sem_vizinho], 0.0, 1.0)
    alpha[alpha < 0.04] = 0.0
    # descontaminação: p = a*c + (1-a)*fundo -> c = (p - (1-a)*fundo) / a
    am = np.maximum(alpha, 1e-3)[..., None]
    limpo = np.clip((lin - (1 - am) * flin) / am, 0.0, 1.0)
    trans = faixa & (alpha > 0) & (alpha < 0.999)
    cor = rgb.astype(np.float32) / 255.0
    cor = np.where(trans[..., None], linear_para_srgb(limpo), cor)
    out = np.dstack([cor * 255.0, alpha * 255.0]).round().clip(0, 255).astype(np.uint8)
    return Image.fromarray(out, "RGBA"), True


def _lab_para_rgb(lab: np.ndarray) -> np.ndarray:
    """Lab (D65) -> sRGB 0-1."""
    L, A, B = lab[..., 0], lab[..., 1], lab[..., 2]
    fy = (L + 16) / 116
    fx = fy + A / 500
    fz = fy - B / 200
    def inv(f):
        return np.where(f ** 3 > 0.008856, f ** 3, (f - 16 / 116) / 7.787)
    xyz = np.stack([inv(fx) * 0.95047, inv(fy), inv(fz) * 1.08883], axis=-1)
    M = np.array([[3.2406, -1.5372, -0.4986], [-0.9689, 1.8758, 0.0415], [0.0557, -0.2040, 1.0570]], np.float32)
    lin = np.clip(xyz @ M.T, 0, 1)
    return linear_para_srgb(lin)


def carregar_estampa(caminho, cfg: Optional[dict] = None) -> Tuple[Image.Image, bool]:
    """Arte pronta para estampar: RGBA, fundo liso removido se não tiver transparência, bordas cortadas.

    Retorna (RGBA, fundo_removido).
    """
    im = carregar_imagem(caminho)
    removido = False
    if not tem_transparencia(im):
        fcfg = (cfg or {}).get("fundo_estampa", {})
        im, removido = remover_fundo(im, float(fcfg.get("tolerancia", 16.0)), float(fcfg.get("buracos_area_max", 0.004)))
    return recortar_alpha(im.convert("RGBA")), removido


def residuo_de_fundo(im: Image.Image) -> Optional[str]:
    """Procura restos de fundo numa arte já sem fundo (antes de estampar).

    Resto típico de uma remoção que falhou: mancha grande, sem cor (cinza/preto), lisa e em degradê
    (nuvem cinza, faixa escura na borda). Tinta de verdade com pouca cor (texto preto/branco) tem
    bordas nítidas ou é chapada; por isso a regra exige as três coisas: pouca cor, degradê e nenhum
    contorno nítido. Retorna a explicação (em português) ou None.
    """
    rgba = im.convert("RGBA")
    s = 256.0 / max(rgba.size)
    if s < 1.0:
        rgba = rgba.resize((max(1, round(rgba.size[0] * s)), max(1, round(rgba.size[1] * s))), Image.BILINEAR)
    arr = np.asarray(rgba)
    a = arr[..., 3].astype(np.float32) / 255.0
    lab = rgb_para_lab(arr[..., :3].astype(np.float32) / 255.0)
    L = lab[..., 0]
    C = np.hypot(lab[..., 1], lab[..., 2])
    gy, gx = np.gradient(L)
    g = np.hypot(gx, gy)
    comp = rotular(a > 0.5)
    h, w = a.shape
    achados = []
    for i in range(comp.n):
        c = comp.rotulos == i + 1
        area = float(c.sum()) / float(h * w)
        if area < 0.04:
            continue
        p5, p95 = np.percentile(L[c], [5, 95])
        if float(np.median(C[c])) < 12.0 and (p95 - p5) >= 12.0 and float(np.percentile(g[c], 95)) < 5.0:
            achados.append(area)
    if not achados:
        return None
    return (f"a arte ficou com restos do fundo ({len(achados)} mancha(s) cinza em degradê, "
            f"{100 * sum(achados):.0f}% da área): a remoção do fundo falhou")


def ler_ajuste_tinta(texto: str) -> Optional[Tuple[float, float, float]]:
    """'L=+12;a=-2;b=-18' -> (12, -2, -18). Vazio ou inválido -> None."""
    vals = {"l": 0.0, "a": 0.0, "b": 0.0}
    achou = False
    for parte in str(texto or "").replace(",", ";").split(";"):
        if "=" not in parte:
            continue
        k, v = parte.split("=", 1)
        k = k.strip().lower()
        if k in vals:
            try:
                vals[k] = float(v.strip())
                achou = True
            except ValueError:
                pass
    return (vals["l"], vals["a"], vals["b"]) if achou else None


def ajustar_tinta(im: Image.Image, ajuste: Tuple[float, float, float]) -> Image.Image:
    """Desloca a cor da tinta principal da arte (Lab). Cores longe da tinta principal (um texto
    preto pequeno numa arte azul, por exemplo) mudam pouco: o peso cai com a distância de cor."""
    rgba = np.asarray(im.convert("RGBA"))
    a = rgba[..., 3]
    lab = rgb_para_lab(rgba[..., :3].astype(np.float32) / 255.0)
    opaco = a > 150
    if opaco.sum() < 20:
        return im
    ref = np.median(lab[opaco], axis=0)
    dist = np.linalg.norm(lab - ref, axis=-1)
    peso = np.exp(-(dist / 30.0) ** 2)[..., None]
    novo = lab + peso * np.array(ajuste, np.float32)
    novo[..., 0] = np.clip(novo[..., 0], 0, 100)
    rgb = _lab_para_rgb(novo)
    out = np.dstack([np.clip(rgb * 255.0 + 0.5, 0, 255).astype(np.uint8), a])
    return Image.fromarray(out, "RGBA")
