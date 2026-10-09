"""Aplicação realista da estampa no mockup liso (numpy + Pillow).

Ideia: a tinta recebe a mesma luz do tecido (sombras e brilhos das dobras), entorta um pouco
seguindo as dobras, ganha a textura da malha e fica presa à silhueta da peça.
Fora da estampa, os pixels do mockup ficam idênticos (byte a byte).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
from PIL import Image

from imagem import (Torso, carregar_imagem, cor_tecido, desfocar, erodir, linear_para_srgb, preparar_peca,
                    srgb_para_linear)


@dataclass
class MockupPreparado:
    caminho: str
    imagem: Image.Image          # RGB ou RGBA (8 bits, sRGB)
    rgb: np.ndarray              # HxWx3 uint8
    alpha: Optional[np.ndarray]  # HxW uint8 se o mockup tem transparência
    mascara: np.ndarray          # HxW bool: onde é tecido
    torso: Torso
    rgb_tecido: Tuple[int, int, int]
    lum_ref: float               # luminância linear típica do tecido (mediana robusta)


def _luminancia(lin: np.ndarray) -> np.ndarray:
    return lin[..., 0] * 0.2126 + lin[..., 1] * 0.7152 + lin[..., 2] * 0.0722


def preparar_mockup(fonte, cfg: dict, torso_manual: Optional[dict] = None, lado_max: Optional[int] = None) -> MockupPreparado:
    """Abre o mockup liso, acha a peça e o tronco. Feito uma vez por mockup (cada worker guarda em cache)."""
    im = fonte if isinstance(fonte, Image.Image) else carregar_imagem(fonte)
    if lado_max and max(im.size) > lado_max:
        s = lado_max / float(max(im.size))
        im = im.resize((max(1, round(im.size[0] * s)), max(1, round(im.size[1] * s))), Image.LANCZOS)
    seg, torso = preparar_peca(im, cfg, torso_manual)
    W, H = im.size
    m_red = Image.fromarray((seg.mascara * 255).astype(np.uint8), "L")
    mascara = np.asarray(m_red.resize((W, H), Image.BILINEAR)) > 127
    alpha = np.asarray(im.getchannel("A")) if im.mode == "RGBA" else None
    if alpha is not None:
        mascara &= alpha > 128
    rgb = np.asarray(im.convert("RGB"))
    t_red = torso.escalar(seg.escala)
    rgb_tec = cor_tecido(seg.rgb, seg.mascara, t_red)
    # luminância de referência: mediana no miolo do tronco
    y0, y1 = int(torso.axila), int(torso.base - 0.05 * torso.altura)
    x0, x1 = int(torso.x0 + 0.1 * torso.largura), int(torso.x1 - 0.1 * torso.largura)
    reg = rgb[max(0, y0):max(y0 + 1, y1):4, max(0, x0):max(x0 + 1, x1):4].astype(np.float32) / 255.0
    lum = _luminancia(srgb_para_linear(reg))
    lum_ref = float(np.median(lum)) if lum.size else 0.5
    return MockupPreparado(str(fonte) if not isinstance(fonte, Image.Image) else "", im, rgb, alpha, mascara,
                           torso, rgb_tec, max(lum_ref, 1e-4))


def redimensionar_premultiplicado(estampa: Image.Image, w: int, h: int) -> Tuple[np.ndarray, np.ndarray]:
    """LANCZOS com alfa pré-multiplicado (sem franja escura/clara). Retorna (rgb_premult 0-1, alfa 0-1)."""
    rgba = np.asarray(estampa.convert("RGBA")).astype(np.float32) / 255.0
    a = rgba[..., 3]
    canais = [rgba[..., i] * a for i in range(3)] + [a]
    out = []
    for c in canais:
        r = Image.fromarray(c.astype(np.float32), "F").resize((w, h), Image.LANCZOS)
        out.append(np.asarray(r, dtype=np.float32))
    alfa = np.clip(out[3], 0.0, 1.0)
    rgb = np.clip(np.stack(out[:3], axis=-1), 0.0, None)
    rgb = np.minimum(rgb, alfa[..., None])
    return rgb, alfa


def _amostrar_bilinear(img: np.ndarray, ys: np.ndarray, xs: np.ndarray) -> np.ndarray:
    """Amostra img (HxW ou HxWxC) nas posições (ys, xs) com interpolação bilinear; fora = 0."""
    h, w = img.shape[:2]
    x0 = np.floor(xs).astype(np.int64)
    y0 = np.floor(ys).astype(np.int64)
    fx = (xs - x0).astype(np.float32)
    fy = (ys - y0).astype(np.float32)
    if img.ndim == 3:
        fx = fx[..., None]
        fy = fy[..., None]
    pad = np.pad(img, ((1, 1), (1, 1)) + (((0, 0),) if img.ndim == 3 else ()))
    x0c = np.clip(x0 + 1, 0, w + 1)
    x1c = np.clip(x0 + 2, 0, w + 1)
    y0c = np.clip(y0 + 1, 0, h + 1)
    y1c = np.clip(y0 + 2, 0, h + 1)
    a = pad[y0c, x0c]
    b = pad[y0c, x1c]
    c = pad[y1c, x0c]
    d = pad[y1c, x1c]
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def aplicar_estampa(mk: MockupPreparado, estampa: Image.Image, caixa: Tuple[float, float, float, float],
                    cfg: dict) -> Image.Image:
    """Estampa a arte (RGBA, já recortada nas bordas transparentes) na caixa (x, y, largura, altura) do mockup."""
    r = cfg["realismo"]
    x, y, w, h = caixa
    pw, ph = max(1, int(round(w))), max(1, int(round(h)))
    px, py = int(round(x)), int(round(y))
    H, W = mk.rgb.shape[:2]
    tw = mk.torso.largura
    dmax = min(float(r.get("deslocamento_max_px", 7.0)), max(1.0, float(r.get("deslocamento_max_rel", 0.006)) * max(pw, ph)))
    sig_dobra = max(1.5, float(r.get("sigma_dobras_rel", 0.006)) * tw)
    m = int(math.ceil(dmax + 3 * sig_dobra)) + 3
    # recorte de trabalho (só a área da estampa + margem)
    cx0, cy0 = max(0, px - m), max(0, py - m)
    cx1, cy1 = min(W, px + pw + m), min(H, py + ph + m)
    if cx1 <= cx0 or cy1 <= cy0:
        return mk.imagem.copy()
    fab = mk.rgb[cy0:cy1, cx0:cx1].astype(np.float32) / 255.0
    fab_lin = srgb_para_linear(fab)
    lum = _luminancia(fab_lin)
    ch, cw = lum.shape

    # estampa redimensionada (pré-multiplicada) num quadro do tamanho do recorte
    ep_rgb, ep_a = redimensionar_premultiplicado(estampa, pw, ph)
    quadro_rgb = np.zeros((ch, cw, 3), np.float32)
    quadro_a = np.zeros((ch, cw), np.float32)
    ox, oy = px - cx0, py - cy0
    sx0, sy0 = max(0, -ox), max(0, -oy)
    dx0, dy0 = max(0, ox), max(0, oy)
    ww = min(pw - sx0, cw - dx0)
    hh = min(ph - sy0, ch - dy0)
    if ww <= 0 or hh <= 0:
        return mk.imagem.copy()
    quadro_rgb[dy0:dy0 + hh, dx0:dx0 + ww] = ep_rgb[sy0:sy0 + hh, sx0:sx0 + ww]
    quadro_a[dy0:dy0 + hh, dx0:dx0 + ww] = ep_a[sy0:sy0 + hh, sx0:sx0 + ww]

    # luz das dobras: sombra multiplica, brilho soma um pouco (funciona em claro e escuro)
    ref = mk.lum_ref
    lum_suave = desfocar(lum, sig_dobra)
    razao = lum_suave / ref
    sombra = np.where(razao < 1.0, np.power(np.clip(razao, 0.35, 1.0), float(r.get("forca_sombra", 0.9))),
                      1.0 + (np.minimum(razao, 1.6) - 1.0) * float(r.get("forca_luz", 0.35)))
    brilho = np.maximum(lum_suave - ref, 0.0) * float(r.get("brilho_tecido", 0.25))
    # textura da malha (passa-alta da luminância)
    passa_alta = lum - desfocar(lum, 1.2)
    textura = 1.0 + float(r.get("forca_textura", 0.55)) * passa_alta / max(ref, 0.12)

    # deslocamento: a arte "escorrega" levemente para dentro das dobras
    gy, gx = np.gradient(desfocar(lum, sig_dobra * 1.5))
    k = float(r.get("forca_deslocamento", 1.0)) * 0.3 * tw / max(ref, 0.05)
    dx = np.clip(-gx * k, -dmax, dmax)
    dy = np.clip(-gy * k, -dmax, dmax)
    yy, xx = np.mgrid[0:ch, 0:cw].astype(np.float32)
    ink_rgb = _amostrar_bilinear(quadro_rgb, yy + dy, xx + dx)
    ink_a = np.clip(_amostrar_bilinear(quadro_a, yy + dy, xx + dx), 0.0, 1.0)

    # borda levemente macia (~0.5 px) e presa à silhueta
    sb = float(r.get("suavizar_borda_px", 0.5))
    if sb > 0:
        ink_rgb = desfocar(ink_rgb, sb)
        ink_a = desfocar(ink_a, sb)
    peca = mk.mascara[cy0:cy1, cx0:cx1]
    peca_suave = desfocar(erodir(peca, 1).astype(np.float32), 0.8)
    a = ink_a * float(r.get("opacidade_tinta", 0.95)) * peca_suave

    cor = ink_rgb / np.maximum(ink_a, 1e-4)[..., None]
    cor_lin = srgb_para_linear(np.clip(cor, 0.0, 1.0))
    cor_lin = cor_lin * (sombra * textura)[..., None] + brilho[..., None]
    out_lin = fab_lin * (1.0 - a[..., None]) + cor_lin * a[..., None]
    out = np.clip(linear_para_srgb(out_lin) * 255.0 + 0.5, 0, 255).astype(np.uint8)

    escrever = a > 0.002
    novo = mk.rgb.copy()
    reg = novo[cy0:cy1, cx0:cx1]
    reg[escrever] = out[escrever]
    if mk.alpha is not None:
        return Image.fromarray(np.dstack([novo, mk.alpha]), "RGBA")
    return Image.fromarray(novo, "RGB")
