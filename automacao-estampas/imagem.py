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
    ys, xs = np.nonzero(a > limiar)
    if len(xs) == 0:
        return im
    return im.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))


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
    h, w, _ = rgb.shape
    lab = rgb_para_lab(desfocar(rgb.astype(np.float32), 0.7))
    borda = np.zeros((h, w), bool)
    b = max(2, int(0.006 * max(h, w)))
    borda[:b, :] = borda[-b:, :] = True
    borda[:, :b] = borda[:, -b:] = True
    fundo = np.median(lab[borda], axis=0)
    spread = np.median(np.abs(lab[borda] - fundo), axis=0)
    tol = max(float(acfg.get("tolerancia_fundo", 14.0)), 4.0 * float(np.linalg.norm(spread)))
    dif = lab - fundo
    dist = np.linalg.norm(dif, axis=-1)
    croma = np.linalg.norm(dif[..., 1:], axis=-1)
    # sombra projetada: mesma cor do fundo, só mais escura e suave
    sombra = (croma < tol * 0.5) & (dif[..., 0] < 0) & (lab[..., 0] > fundo[0] * 0.55)
    L = lab[..., 0]
    gy, gx = np.gradient(desfocar(L, 0.8))
    grad = np.hypot(gx, gy)
    limiar_grad = max(2.2, float(np.percentile(grad[borda], 99)) * 2.5)
    permitido = ((dist < tol) | sombra) & (grad < limiar_grad)
    fundo_m = propagar(borda & permitido, permitido)
    peca = ~fundo_m
    peca = _limpar_mascara(peca)
    fr = tuple(int(v) for v in np.median(rgb[borda], axis=0))
    return Segmentacao(peca, s, rgb, fr, False)


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
        if c.especial:
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
                     gola_rel: float = 0.0) -> Optional[EstampaDetectada]:
    """Acha a tinta dentro do tronco: pixels que fogem da cor do tecido (compensando dobras)."""
    acfg = cfg["analise"]
    peq, s = _reduzir(im, int(acfg.get("lado_max_estampa", 1200)))
    t = torso.escalar(s)
    W, H = peq.size
    x0 = int(max(0, t.x0 + 0.03 * t.largura))
    x1 = int(min(W, t.x1 - 0.03 * t.largura))
    y0 = int(max(0, t.topo + max(gola_rel * t.largura, 0.03 * t.largura) + 0.012 * t.largura))
    y1 = int(min(H, t.base - 0.015 * t.altura))
    if x1 - x0 < 10 or y1 - y0 < 10:
        return None
    rgb = np.asarray(peq.convert("RGB"))[y0:y1, x0:x1]
    lab = rgb_para_lab(rgb)
    ref = rgb_para_lab(np.array([rgb_tecido], np.uint8))[0]
    pl = float(acfg.get("peso_luminancia", 0.55))
    d0 = np.linalg.norm((lab - ref) * np.array([pl, 1, 1], np.float32), axis=-1)
    lim_min = float(acfg.get("limiar_estampa_min", 13.0))
    # 1a passada: candidatos grosseiros; 2a: luminância local do tecido (tira dobras/sombras)
    cand = dilatar(d0 > lim_min, max(1, int(0.006 * t.largura)))
    peso = (~cand).astype(np.float32)
    sig = 0.035 * t.largura
    L_loc = desfocar(lab[..., 0] * peso, sig) / np.maximum(desfocar(peso, sig), 1e-3)
    L_loc = np.where(desfocar(peso, sig) > 0.05, L_loc, ref[0])
    dif = lab - ref
    dif[..., 0] = lab[..., 0] - L_loc
    d = np.linalg.norm(dif * np.array([pl, 1, 1], np.float32), axis=-1)
    base = d[~cand] if (~cand).sum() > 100 else d.ravel()
    med = float(np.median(base))
    mad = float(np.median(np.abs(base - med))) * 1.4826
    limiar = max(lim_min, med + 4.0 * mad)
    m = d > limiar
    # limpeza: fecha traços de letras, remove pontinhos
    rc = max(1, int(round(0.004 * t.largura)))
    m = erodir(dilatar(m, rc), rc) & (d > limiar * 0.5)
    comp = rotular(m)
    area_torso = t.largura * t.altura
    amin = float(acfg.get("area_min_componente", 0.00025)) * area_torso
    manter = []
    for i in range(comp.n):
        bx0, by0, bx1, by1 = comp.bbox[i]
        if comp.area[i] < amin or (bx1 - bx0) < 3 or (by1 - by0) < 3:
            continue
        manter.append(i)
    if not manter:
        return None
    bb = comp.bbox[manter]
    bx0, by0 = bb[:, 0].min() + x0, bb[:, 1].min() + y0
    bx1, by1 = bb[:, 2].max() + x0, bb[:, 3].max() + y0
    k = 1.0 / s
    area = float(comp.area[manter].sum()) / area_torso
    return EstampaDetectada((int(round(bx0 * k)), int(round(by0 * k)), int(round(bx1 * k)), int(round(by1 * k))),
                            round(area, 5), len(manter))


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
    return seg, torso


def analisar_imagem(fonte, cfg: dict, margem_recorte: float = 0.06) -> AnaliseImagem:
    """Analisa uma foto atual da loja: tronco, cor do tecido, decote e estampa (posição e tamanho)."""
    im = fonte if isinstance(fonte, Image.Image) else carregar_imagem(fonte)
    seg, torso = preparar_peca(im, cfg)
    t_red = torso.escalar(seg.escala)
    rgb_tec = cor_tecido(seg.rgb, seg.mascara, t_red)
    cor = classificar_cor(rgb_tec, cfg)
    gola = medir_gola(seg.rgb, seg.mascara, t_red, rgb_tec)
    est = detectar_estampa(im, torso, rgb_tec, cfg, gola)
    geo = geometria_relativa(est.bbox, torso) if est else None
    rec = None
    if est:
        x0, y0, x1, y1 = est.bbox
        mg = margem_recorte * max(x1 - x0, y1 - y0)
        rec = im.convert("RGB").crop((int(max(0, x0 - mg)), int(max(0, y0 - mg)),
                                      int(min(im.size[0], x1 + mg)), int(min(im.size[1], y1 + mg))))
    return AnaliseImagem(im.size[0], im.size[1], torso, rgb_tec, cor, gola, est, geo, rec)


def remover_fundo(im: Image.Image, tolerancia: float = 18.0) -> Tuple[Image.Image, bool]:
    """Arte sem transparência (JPG...): tira a cor lisa da borda por flood fill a partir das bordas.

    Mantém brancos internos (só some o que encosta na borda). Retorna (RGBA, removeu?).
    """
    rgb = np.asarray(im.convert("RGB"))
    h, w, _ = rgb.shape
    lab = rgb_para_lab(rgb)
    borda = np.zeros((h, w), bool)
    borda[0, :] = borda[-1, :] = True
    borda[:, 0] = borda[:, -1] = True
    fundo = np.median(lab[borda], axis=0)
    if np.median(np.linalg.norm(lab[borda] - fundo, axis=-1)) > tolerancia:
        return im.convert("RGBA"), False  # borda não é lisa: não mexe
    dist = np.linalg.norm(lab - fundo, axis=-1)
    fora = propagar(borda & (dist < tolerancia), dist < tolerancia)
    if fora.mean() < 0.02:
        return im.convert("RGBA"), False
    # alpha suave na transição (antisserrilhado) + "descontaminação" da cor do fundo
    a = np.clip((dist - tolerancia * 0.35) / (tolerancia * 0.65), 0, 1).astype(np.float32)
    perto = dilatar(fora, 1)
    alpha = np.where(fora & ~(perto & ~erodir(fora, 1)), 0.0, 1.0).astype(np.float32)
    borda_t = perto & ~erodir(fora, 1)
    alpha[borda_t] = a[borda_t]
    alpha[~perto] = 1.0
    cor = rgb.astype(np.float32)
    fr = np.median(rgb[borda], axis=0).astype(np.float32)
    am = np.maximum(alpha, 1e-3)[..., None]
    cor = np.where(borda_t[..., None], np.clip((cor - fr * (1 - am)) / am, 0, 255), cor)
    out = np.dstack([cor, alpha * 255]).round().astype(np.uint8)
    return Image.fromarray(out, "RGBA"), True
