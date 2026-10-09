"""Aplicação realista da estampa no mockup liso (numpy + Pillow) e enquadramento da imagem final.

Ideia: a tinta recebe a mesma luz do tecido (sombras e brilhos das dobras), entorta um pouco
seguindo as dobras, ganha a textura da malha e fica presa à silhueta da peça.
Fora da estampa, os pixels do mockup ficam idênticos (byte a byte).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
from PIL import Image, ImageFilter

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
    escala: float = 1.0          # imagem usada / arquivo original (prévia usa < 1)


def _luminancia(lin: np.ndarray) -> np.ndarray:
    return lin[..., 0] * 0.2126 + lin[..., 1] * 0.7152 + lin[..., 2] * 0.0722


def preparar_mockup(fonte, cfg: dict, torso_manual: Optional[dict] = None, lado_max: Optional[int] = None,
                    torso_de: Optional[Torso] = None) -> MockupPreparado:
    """Abre o mockup liso, acha a peça e o tronco. Feito uma vez por mockup (cada worker guarda em cache).

    torso_de: usar este tronco (já na escala desta imagem) em vez de medir — o close-costas não tem
    tronco visível, então recebe o das costas mapeado pelo registro.
    """
    im = fonte if isinstance(fonte, Image.Image) else carregar_imagem(fonte)
    escala = 1.0
    if lado_max and max(im.size) > lado_max:
        escala = lado_max / float(max(im.size))
        im = im.resize((max(1, round(im.size[0] * escala)), max(1, round(im.size[1] * escala))), Image.LANCZOS)
    W, H = im.size
    alpha = np.asarray(im.getchannel("A")) if im.mode == "RGBA" else None
    rgb = np.asarray(im.convert("RGB"))
    if torso_de is not None:
        torso = torso_de
        mascara = alpha > 128 if alpha is not None else np.ones((H, W), bool)
        miolo = rgb[mascara][::7]
        rgb_tec = tuple(int(v) for v in np.median(miolo, axis=0)) if len(miolo) else (128, 128, 128)
        reg = rgb[mascara][::5].astype(np.float32) / 255.0
    else:
        seg, torso = preparar_peca(im, cfg, torso_manual)
        m_red = Image.fromarray((seg.mascara * 255).astype(np.uint8), "L")
        mascara = np.asarray(m_red.resize((W, H), Image.BILINEAR)) > 127
        if alpha is not None:
            mascara = alpha > 128
        t_red = torso.escalar(seg.escala)
        rgb_tec = cor_tecido(seg.rgb, seg.mascara, t_red)
        y0, y1 = int(torso.axila), int(torso.base - 0.05 * torso.altura)
        x0, x1 = int(torso.x0 + 0.1 * torso.largura), int(torso.x1 - 0.1 * torso.largura)
        reg = rgb[max(0, y0):max(y0 + 1, y1):4, max(0, x0):max(x0 + 1, x1):4].astype(np.float32) / 255.0
    lum = _luminancia(srgb_para_linear(reg))
    lum_ref = float(np.median(lum)) if lum.size else 0.5
    return MockupPreparado(str(fonte) if not isinstance(fonte, Image.Image) else "", im, rgb, alpha, mascara,
                           torso, rgb_tec, max(lum_ref, 1e-4), escala)


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
                    cfg: dict, base: Optional[np.ndarray] = None, escala_detalhe: float = 1.0) -> Image.Image:
    """Estampa a arte (RGBA, já recortada nas bordas transparentes) na caixa (x, y, largura, altura) do mockup.

    base: rgb já com outra estampa (para frente+costas na mesma imagem não acontece, mas fica genérico).
    escala_detalhe: px desta imagem por px do mockup "normal" (o close-costas é ~1.9x): ajusta o
    tamanho das dobras/deslocamento para o close ter o mesmo aspecto físico.
    """
    r = cfg["realismo"]
    x, y, w, h = caixa
    pw, ph = max(1, int(round(w))), max(1, int(round(h)))
    px, py = int(math.floor(x)), int(math.floor(y))
    H, W = mk.rgb.shape[:2]
    fonte_rgb = mk.rgb if base is None else base
    # tamanho físico de referência: largura do tronco (no close já vem ampliada pelo registro)
    tw = mk.torso.largura
    k_det = max(escala_detalhe, 1e-6)
    dmax = float(r.get("deslocamento_max_rel", 0.006)) * tw
    dmax = min(dmax, float(r.get("deslocamento_max_px", 7.0)) * k_det * mk.escala)
    dmax = max(dmax, 0.5)
    sig_dobra = max(1.5, float(r.get("sigma_dobras_rel", 0.006)) * tw)
    m = int(math.ceil(dmax + 3 * sig_dobra)) + 3
    cx0, cy0 = max(0, px - m), max(0, py - m)
    cx1, cy1 = min(W, px + pw + m), min(H, py + ph + m)
    if cx1 <= cx0 or cy1 <= cy0:
        return _como_imagem(mk, fonte_rgb.copy())
    fab = fonte_rgb[cy0:cy1, cx0:cx1].astype(np.float32) / 255.0
    fab_lin = srgb_para_linear(fab)
    lum = _luminancia(srgb_para_linear(mk.rgb[cy0:cy1, cx0:cx1].astype(np.float32) / 255.0))
    ch, cw = lum.shape

    # estampa redimensionada (pré-multiplicada) num quadro do tamanho do recorte, com posição sub-pixel
    ep_rgb, ep_a = redimensionar_premultiplicado(estampa, pw, ph)
    quadro_rgb = np.zeros((ch, cw, 3), np.float32)
    quadro_a = np.zeros((ch, cw), np.float32)
    ox, oy = px - cx0, py - cy0
    sx0, sy0 = max(0, -ox), max(0, -oy)
    dx0, dy0 = max(0, ox), max(0, oy)
    ww = min(pw - sx0, cw - dx0)
    hh = min(ph - sy0, ch - dy0)
    if ww <= 0 or hh <= 0:
        return _como_imagem(mk, fonte_rgb.copy())
    quadro_rgb[dy0:dy0 + hh, dx0:dx0 + ww] = ep_rgb[sy0:sy0 + hh, sx0:sx0 + ww]
    quadro_a[dy0:dy0 + hh, dx0:dx0 + ww] = ep_a[sy0:sy0 + hh, sx0:sx0 + ww]
    fx, fy = x - px, y - py  # fração de pixel da posição

    # --- luz das dobras -------------------------------------------------------------
    # razão entre a luz local (desfocada) e a luz típica do tecido: <1 sombra, >1 brilho.
    ref = mk.lum_ref
    lum_suave = desfocar(lum, sig_dobra)
    razao = np.clip(lum_suave / ref, 0.2, 3.0)
    fs = float(r.get("forca_sombra", 0.9))
    fl = float(r.get("forca_luz", 0.35))
    sombra = np.where(razao < 1.0, np.power(razao, fs), 1.0 + (np.minimum(razao, 1.8) - 1.0) * fl)
    # brilho especular do tecido (só onde o tecido é mais claro que o normal): soma um pouco de luz
    brilho = np.maximum(lum_suave - ref, 0.0) * float(r.get("brilho_tecido", 0.25))
    # --- textura da malha: passa-alta da luminância em escala perceptual (vale p/ claro e escuro)
    L_perc = np.power(np.clip(lum, 0, 1), 1 / 2.2)
    sig_tex = max(0.8, 1.2 * k_det * mk.escala)
    passa_alta = L_perc - desfocar(L_perc, sig_tex)
    textura = 1.0 + float(r.get("forca_textura", 0.55)) * 2.5 * passa_alta
    textura = np.clip(textura, 0.85, 1.15)

    # --- deslocamento: a arte "escorrega" levemente para dentro das dobras -------------
    gy, gx = np.gradient(desfocar(np.log(np.maximum(lum, 1e-4)), sig_dobra * 1.5))
    kdesl = float(r.get("forca_deslocamento", 1.0)) * 0.6 * sig_dobra
    dx = np.clip(-gx * kdesl * sig_dobra, -dmax, dmax)
    dy = np.clip(-gy * kdesl * sig_dobra, -dmax, dmax)
    yy, xx = np.mgrid[0:ch, 0:cw].astype(np.float32)
    sy = yy + dy - fy
    sx = xx + dx - fx
    ink_rgb = _amostrar_bilinear(quadro_rgb, sy, sx)
    ink_a = np.clip(_amostrar_bilinear(quadro_a, sy, sx), 0.0, 1.0)

    # borda levemente macia (~0.5 px) e presa à silhueta
    sb = float(r.get("suavizar_borda_px", 0.5)) * max(1.0, k_det * mk.escala)
    if sb > 0.3:
        ink_rgb = desfocar(ink_rgb, sb)
        ink_a = desfocar(ink_a, sb)
    peca = mk.mascara[cy0:cy1, cx0:cx1]
    if mk.alpha is not None:
        peca_suave = (mk.alpha[cy0:cy1, cx0:cx1].astype(np.float32) / 255.0)
        peca_suave = np.where(erodir(peca, 1), peca_suave, peca_suave * peca_suave)
    else:
        peca_suave = desfocar(erodir(peca, 1).astype(np.float32), 0.8)
    a = np.clip(ink_a * float(r.get("opacidade_tinta", 0.95)) * peca_suave, 0.0, 1.0)

    cor = ink_rgb / np.maximum(ink_a, 1e-4)[..., None]
    cor_lin = srgb_para_linear(np.clip(cor, 0.0, 1.0))
    cor_lin = cor_lin * (sombra * textura)[..., None] + brilho[..., None]
    # luz em espaço linear (física), mas a cobertura da tinta em espaço perceptual: misturar 5% de
    # tecido branco em linear deixaria o preto cinza (~60/255); a tinta de verdade cobre bem.
    tinta = linear_para_srgb(cor_lin)
    # granulado da tinta sobre a malha (o mockup liso quase não tem textura visível): ruído fino,
    # fixo (semente), do tamanho do fio da malha na escala desta imagem
    gr = float(r.get("granulado_tinta", 0.018))
    if gr > 0:
        rng = np.random.default_rng(12345 + ch * 7 + cw)
        ruido = desfocar(rng.standard_normal((ch, cw)).astype(np.float32), max(0.5, 0.6 * k_det * mk.escala))
        ruido /= max(float(ruido.std()), 1e-6)
        tinta = np.clip(tinta + (gr * ruido)[..., None] * (0.35 + 0.65 * tinta), 0.0, 1.0)
    out_s = fab * (1.0 - a[..., None]) + tinta * a[..., None]
    out = np.clip(out_s * 255.0 + 0.5, 0, 255).astype(np.uint8)

    escrever = a > 0.002
    novo = fonte_rgb.copy()
    reg = novo[cy0:cy1, cx0:cx1]
    reg[escrever] = out[escrever]
    return _como_imagem(mk, novo)


def _como_imagem(mk: MockupPreparado, rgb: np.ndarray) -> Image.Image:
    if mk.alpha is not None:
        return Image.fromarray(np.dstack([rgb, mk.alpha]), "RGBA")
    return Image.fromarray(rgb, "RGB")


# ---------------------------------------------------------------------------
# Enquadramento (igual às fotos da loja)
# ---------------------------------------------------------------------------

def _bbox_alpha(im: Image.Image) -> Tuple[int, int, int, int]:
    if im.mode != "RGBA":
        return (0, 0, im.size[0], im.size[1])
    a = np.asarray(im.getchannel("A"))
    ys, xs = np.nonzero(a > 16)
    if len(xs) == 0:
        return (0, 0, im.size[0], im.size[1])
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def enquadrar(im: Image.Image, cfg: dict, lado: Optional[int] = None, foco_y: Optional[float] = None,
              eh_close: bool = False) -> Tuple[Image.Image, Optional[Image.Image]]:
    """Coloca a peça (RGBA) no quadro padrão da loja. Retorna (imagem final RGB/RGBA, master transparente).

    - formato "quadrado": lado x lado, peça escalada para ocupar a mesma fração do quadro que nas fotos
      atuais (ocupacao_largura/ocupacao_altura) e centralizada em "centro".
    - formato "original": mantém o tamanho do mockup, só troca o fundo.
    - close-costas: "preencher" corta um quadrado cheio (centrado em foco_y, a altura da estampa);
      "inteiro" encaixa a imagem toda no quadrado.
    """
    e = cfg["enquadramento"]
    lado = int(lado or e.get("lado", 2048))
    fundo_cor = tuple(int(v) for v in e.get("cor_fundo", [237, 237, 237]))
    transparente = e.get("fundo", "cor") == "transparente"
    im = im.convert("RGBA")
    if e.get("formato", "quadrado") == "original":
        tela = im
    elif eh_close:
        W, H = im.size
        if e.get("close", "preencher") == "preencher":
            q = min(W, H)
            cy = foco_y if foco_y is not None else H / 2.0
            y0 = int(round(min(max(0.0, cy - q / 2.0), H - q)))
            x0 = (W - q) // 2
            tela = im.crop((x0, y0, x0 + q, y0 + q)).resize((lado, lado), Image.LANCZOS)
        else:
            s = lado / float(max(W, H))
            peq = im.resize((max(1, round(W * s)), max(1, round(H * s))), Image.LANCZOS)
            tela = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
            tela.alpha_composite(peq, ((lado - peq.size[0]) // 2, (lado - peq.size[1]) // 2))
    else:
        x0, y0, x1, y1 = _bbox_alpha(im)
        pw, ph = x1 - x0, y1 - y0
        s = min(e.get("ocupacao_largura", 0.572) * lado / pw, e.get("ocupacao_altura", 0.590) * lado / ph)
        peca = im.crop((x0, y0, x1, y1))
        nw, nh = max(1, round(pw * s)), max(1, round(ph * s))
        peca = _redimensionar_rgba(peca, nw, nh)
        cx, cy = e.get("centro", [0.501, 0.512])
        tela = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
        tela.alpha_composite(peca, (int(round(cx * lado - nw / 2.0)), int(round(cy * lado - nh / 2.0))))
    master = tela if e.get("salvar_png_transparente", True) else None
    if transparente:
        return tela, master
    fundo = Image.new("RGBA", tela.size, fundo_cor + (255,))
    op = float(e.get("sombra_opacidade", 0.0))
    if op > 0 and not eh_close:
        a = tela.getchannel("A")
        raio = max(2, int(0.012 * tela.size[0]))
        sombra_a = a.filter(ImageFilter.GaussianBlur(raio)).point(lambda v: int(v * op))
        sombra = Image.new("RGBA", tela.size, (0, 0, 0, 0))
        sombra.putalpha(sombra_a)
        fundo.alpha_composite(sombra, (0, int(0.006 * tela.size[1])))
    fundo.alpha_composite(tela)
    return fundo.convert("RGB"), master


def _redimensionar_rgba(im: Image.Image, w: int, h: int) -> Image.Image:
    """Redimensiona RGBA com alfa pré-multiplicado (sem halo escuro na silhueta)."""
    rgb, a = redimensionar_premultiplicado(im, w, h)
    cor = rgb / np.maximum(a, 1e-4)[..., None]
    out = np.dstack([np.clip(cor, 0, 1), a])
    return Image.fromarray(np.clip(out * 255 + 0.5, 0, 255).astype(np.uint8), "RGBA")
