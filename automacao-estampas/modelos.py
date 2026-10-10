"""Mockups com modelo (pessoa vestindo a camiseta): achar a camiseta na foto e estampar por cima.

Diferente do mockup liso, aqui a foto tem pele, cabelo, calça e braços. A camiseta é achada pela cor
do tecido a partir de um ponto no peito/costas (com tolerância maior para luz e sombra do que para
a cor). A estampa só é pintada sobre o que não é pele (braço ou mão na frente cobre a estampa,
como numa foto real). Luz, dobras e textura vêm da própria foto (mesmo compositor dos mockups lisos).
"""
from __future__ import annotations

from collections import deque
from typing import Optional, Tuple

import numpy as np
from PIL import Image, ImageFilter

from compositor import MockupPreparado, _luminancia
from imagem import Torso, carregar_imagem, srgb_para_linear


def _lab(rgb: np.ndarray) -> np.ndarray:
    c = rgb / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = c @ m.T / np.array([0.9505, 1.0, 1.089])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def mascara_camiseta(im: Image.Image, lado: int = 700, semente: Optional[Tuple[float, float]] = None) -> np.ndarray:
    """Máscara (tamanho da foto) da camiseta: região de cor do tecido ligada ao ponto do peito/costas."""
    W, H = im.size
    k = lado / float(max(W, H))
    p = im.convert("RGBA").resize((round(W * k), round(H * k)), Image.BILINEAR)
    arr = np.asarray(p)
    a = arr[..., 3] > 128
    L = _lab(arr[..., :3].astype(np.float32))
    ys, _ = np.nonzero(a)
    top, bot = ys.min(), ys.max()
    h = bot - top
    if semente is not None:
        y0, x0 = int(semente[1] * k), int(semente[0] * k)
    else:
        y0 = int(top + 0.28 * h)
        r = np.nonzero(a[y0])[0]
        x0 = int((r[0] + r[-1]) / 2)
    ref = np.median(L[y0 - 6:y0 + 7, x0 - 6:x0 + 7].reshape(-1, 3), 0)
    peso = np.array([0.35, 2.2, 2.2])  # luz/sombra varia muito; a cor do tecido, pouco
    d = np.linalg.norm((L - ref) * peso, axis=-1)
    viz = d[y0 - 15:y0 + 16, x0 - 15:x0 + 16]
    tol = max(9.0, 2.5 * float(np.percentile(viz, 90)))
    cand = (d < tol) & a
    m = np.zeros(cand.shape, bool)
    fila = deque([(y0, x0)])
    m[y0, x0] = True
    Hh, Ww = cand.shape
    while fila:
        y, x = fila.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            yy, xx = y + dy, x + dx
            if 0 <= yy < Hh and 0 <= xx < Ww and cand[yy, xx] and not m[yy, xx]:
                m[yy, xx] = True
                fila.append((yy, xx))
    im_m = Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))
    return np.asarray(im_m.resize((W, H), Image.BILINEAR)) > 127


def mascara_pele(rgb: np.ndarray) -> np.ndarray:
    """Pele (braço, mão, pescoço): tons quentes de saturação média."""
    L = _lab(rgb.astype(np.float32))
    pele = (L[..., 1] > 7) & (L[..., 2] > 11) & (L[..., 0] > 25) & (L[..., 0] < 88) & (L[..., 1] < 40)
    im = Image.fromarray((pele * 255).astype(np.uint8)).filter(ImageFilter.MedianFilter(5)).filter(ImageFilter.MaxFilter(3))
    return np.asarray(im) > 127


def tronco_da_mascara(m: np.ndarray) -> Torso:
    """Tronco (sem mangas) a partir da máscara da camiseta."""
    H, W = m.shape
    linhas = np.nonzero(m.sum(1) > 0.02 * W)[0]
    top, bot = int(linhas[0]), int(linhas[-1])
    alt = bot - top
    esq = np.full(H, np.nan)
    dir_ = np.full(H, np.nan)
    for y in range(top, bot + 1):
        xs = np.nonzero(m[y])[0]
        if len(xs) > 0.02 * W:
            esq[y], dir_[y] = np.percentile(xs, 2), np.percentile(xs, 98)
    a, b = top + int(0.55 * alt), top + int(0.85 * alt)
    larg = np.nanmedian(dir_[a:b] - esq[a:b])
    cx = np.nanmedian((esq[a:b] + dir_[a:b]) / 2)
    # gola: topo da máscara perto do centro
    c0, c1 = int(cx - 0.3 * larg), int(cx + 0.3 * larg)
    col = m[:, max(0, c0):min(W, c1)]
    tem = col.any(0)
    topo = float(np.percentile(np.argmax(col, 0)[tem], 5)) if tem.any() else float(top)
    base = float(np.percentile(np.nonzero(m[:, int(cx - 0.2 * larg):int(cx + 0.2 * larg)].any(1))[0], 99))
    return Torso(cx - larg / 2, cx + larg / 2, topo, base, topo + 0.3 * (base - topo), W, H)


def preparar_modelo(caminho: str, semente: Optional[Tuple[float, float]] = None,
                    torso_manual: Optional[Torso] = None) -> MockupPreparado:
    im = carregar_imagem(caminho).convert("RGBA")
    W, H = im.size
    rgb = np.asarray(im.convert("RGB"))
    alpha = np.asarray(im.getchannel("A"))
    cam = mascara_camiseta(im, semente=semente)
    torso = torso_manual or tronco_da_mascara(cam)
    # onde a tinta pode ir: pessoa, menos pele (braço/mão na frente cobre a estampa)
    mascara = (alpha > 128) & ~mascara_pele(rgb)
    reg = rgb[cam][::9].astype(np.float32) / 255.0
    lum = _luminancia(srgb_para_linear(reg))
    lum_ref = float(np.median(lum)) if lum.size else 0.5
    rgb_tec = tuple(int(v) for v in np.median(rgb[cam][::9], axis=0))
    return MockupPreparado(caminho, im, rgb, alpha, mascara, torso, rgb_tec, max(lum_ref, 1e-4), 1.0)


def aplicar_estampa_ps(mk: MockupPreparado, estampa: Image.Image, caixa: Tuple[float, float, float, float],
                       deslocar_px: float = 10.0, desfoque_mapa: float = 2.0, opacidade: float = 1.0,
                       realismo: float = 0.0) -> Image.Image:
    """O passo a passo clássico do Photoshop, automatizado:

    1. Filtro > Distorcer > Deslocar (10 x 10) usando a própria foto em preto e branco como mapa:
       a estampa anda até ``deslocar_px`` para os lados e para cima/baixo conforme o claro/escuro do
       tecido, então entorta junto com as dobras.
    2. Modo de mesclagem Multiplicar: estampa x foto. As sombras, dobras e a trama da camiseta
       aparecem por cima da tinta. Em camiseta escura, Multiplicar apagaria a estampa; ali a foto é
       usada normalizada pela cor do tecido (o mesmo efeito de sombra, sem escurecer a tinta).
    """
    from compositor import redimensionar_premultiplicado, _amostrar_bilinear
    x, y, w, h = caixa
    pw, ph = max(1, int(round(w))), max(1, int(round(h)))
    px, py = int(np.floor(x)), int(np.floor(y))
    H, W = mk.rgb.shape[:2]
    m = int(np.ceil(abs(deslocar_px))) + 4
    x0, y0, x1, y1 = max(0, px - m), max(0, py - m), min(W, px + pw + m), min(H, py + ph + m)
    foto = mk.rgb[y0:y1, x0:x1].astype(np.float32) / 255.0
    # mapa de deslocamento: foto em tons de cinza, levemente desfocada (como salvar o PSD em P&B)
    cinza = Image.fromarray((foto.mean(-1) * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(desfoque_mapa))
    mapa = np.asarray(cinza).astype(np.float32) / 255.0
    # Photoshop: 128 = não move; 0 e 255 = movem o máximo em sentidos opostos
    d = (mapa - 0.5) * 2.0 * deslocar_px
    ep_rgb, ep_a = redimensionar_premultiplicado(estampa, pw, ph)
    quad = np.zeros((y1 - y0, x1 - x0, 4), np.float32)
    ox, oy = px - x0, py - y0
    quad[oy:oy + ph, ox:ox + pw, :3] = ep_rgb[:max(0, min(ph, y1 - y0 - oy)), :max(0, min(pw, x1 - x0 - ox))]
    quad[oy:oy + ph, ox:ox + pw, 3] = ep_a[:max(0, min(ph, y1 - y0 - oy)), :max(0, min(pw, x1 - x0 - ox))]
    yy, xx = np.mgrid[0:y1 - y0, 0:x1 - x0].astype(np.float32)
    amost = _amostrar_bilinear(quad, yy - d, xx - d)
    a = np.clip(amost[..., 3], 0, 1) * opacidade
    if realismo > 0:
        from scipy import ndimage
        lum0 = foto.mean(-1)
        fundo = ndimage.gaussian_filter(lum0, 2.5)
        hp = np.clip((lum0 - fundo) / np.maximum(fundo, 0.04), -0.35, 0.35)   # trama/dobra fina do tecido
        # tinta mais fina nos "poros" da trama + grão leve de serigrafia (semente fixa: igual sempre)
        rng = np.random.default_rng(7)
        grao = ndimage.gaussian_filter(rng.standard_normal(a.shape).astype(np.float32), 0.7)
        a = a * np.clip(1 - realismo * (0.9 * np.clip(-hp, 0, 1) + 0.06 * np.abs(grao)), 0, 1)
        a = ndimage.gaussian_filter(a, 0.35 * realismo)                       # borda da tinta, não recorte
    cor = np.where(amost[..., 3:4] > 1e-4, amost[..., :3] / np.maximum(amost[..., 3:4], 1e-4), 0.0)
    cor = np.clip(cor, 0, 1)
    tecido = np.array(mk.rgb_tecido, np.float32) / 255.0
    if tecido.mean() > 0.45:
        # fundo claro que sobrou na arte (creme/branco quase da cor do tecido) não é impresso de verdade
        dif = np.abs(cor - tecido).max(-1)
        a = a * np.clip((dif - 0.07) / 0.08, 0, 1)
    if tecido.mean() > 0.45:
        # camiseta clara: Multiplicar de verdade (tinta x tecido)
        tinta = cor * foto
    else:
        # camiseta escura: sombra relativa ao tom do tecido (multiplicar normalizado), sem apagar a tinta
        lum = foto.mean(-1, keepdims=True)
        rel = np.clip(lum / max(float(tecido.mean()), 1e-3), 1e-3, None)
        # sombra suavizada: dobra funda escurece a tinta, mas sem sumir com ela
        rel = np.clip(rel ** 0.6, 0.6, 1.4)
        tinta = np.clip(cor * rel, 0, 1)
    if realismo > 0:
        # a trama aparece por cima da tinta (em tecido claro o Multiplicar já faz isso)
        tinta = np.clip(tinta * (1 + realismo * (1.2 if tecido.mean() <= 0.45 else 0.4) * hp[..., None]), 0, 1)
    pode = mk.mascara[y0:y1, x0:x1].astype(np.float32)
    a = a * pode
    out = foto * (1 - a[..., None]) + tinta * a[..., None]
    rgb = mk.rgb.copy()
    rgb[y0:y1, x0:x1] = np.clip(out * 255 + 0.5, 0, 255).astype(np.uint8)
    res = Image.fromarray(rgb, "RGB").convert("RGBA")
    if mk.alpha is not None:
        res.putalpha(Image.fromarray(mk.alpha))
    return res


def curvar_estampa(estampa: Image.Image, caixa: Tuple[float, float, float, float], torso: Torso,
                   gola_x: Optional[float] = None, curva: float = 0.55, arco: float = 0.025
                   ) -> Tuple[Image.Image, Tuple[float, float, float, float]]:
    """Dobra a estampa em volta do corpo (cilindro) em vez de deixá-la reta como numa prancha.

    - O tronco é tratado como um cilindro de raio = meia largura do corpo. A estampa é "enrolada" nele:
      no meio fica do tamanho certo, perto das laterais vai encolhendo, como numa foto real.
    - Se o corpo está levemente virado (a gola não está no meio da silhueta), o centro da estampa
      acompanha a linha da coluna/esterno, que é a gola, e o lado mais longe encolhe mais.
    - ``arco``: as linhas descem um pouco nas pontas (caimento do tecido sobre o peito/escápulas).
    Retorna a estampa já deformada e a nova caixa (x, y, w, h) na foto.
    """
    from compositor import redimensionar_premultiplicado
    x, y, w, h = caixa
    R = torso.largura / 2.0
    cx = (torso.x0 + torso.x1) / 2.0
    gx = gola_x if gola_x is not None else cx
    giro = float(np.arcsin(np.clip((gx - cx) / R, -0.6, 0.6)))
    # posição plana (como no mockup) medida a partir da gola: d = distância do centro da caixa até a
    # linha da coluna/esterno. Cada ponto plano s vira um ângulo no cilindro: ang(s) = giro + teta(s).
    d = (x + w / 2.0) - gx
    Rc = R * np.cos(giro) + 1e-6

    def teta(sp):
        return curva * np.arcsin(np.clip(sp / Rc, -0.98, 0.98)) + (1 - curva) * sp / R

    ws, hs = max(2, int(round(w * 2))), max(2, int(round(h * 2)))  # trabalha em 2x para não perder nitidez
    rgb, a = redimensionar_premultiplicado(estampa, ws, hs)
    us = np.linspace(-1, 1, 1024)
    angs = giro + teta(d + us * w / 2.0)                   # crescente em u
    xs_dest = cx + R * np.sin(np.clip(angs, -1.5, 1.5))
    X0, X1 = float(xs_dest.min()), float(xs_dest.max())
    Y0, Y1 = y, y + h + arco * h
    W2, H2 = max(2, int(round((X1 - X0) * 2))), max(2, int(round((Y1 - Y0) * 2)))
    # para cada pixel de destino, acha (u, v) de origem invertendo x(u) por interpolação
    xd = X0 + (np.arange(W2) + 0.5) / 2.0
    u = np.interp(xd, xs_dest, us, left=-2.0, right=2.0)
    ud = (u + 1) / 2 * ws
    yd = Y0 + (np.arange(H2) + 0.5) / 2.0
    uc = (np.arcsin(np.clip((xd - cx) / R, -1, 1)) - giro) / max(1e-3, teta(w / 2.0 + abs(d)))
    caida = arco * h * np.clip(uc, -1, 1) ** 2             # as pontas descem um pouco (mais longe da gola)
    vv = (yd[:, None] - Y0 - caida[None, :]) / h * hs
    uu = np.broadcast_to(ud[None, :], vv.shape)
    from compositor import _amostrar_bilinear
    quad = np.dstack([rgb, a])
    amost = _amostrar_bilinear(quad, vv - 0.5, uu - 0.5)
    fora = (np.abs(u) > 1.0)[None, :] | (vv < 0) | (vv > hs)
    amost[fora] = 0
    arr = np.clip(amost * 255 + 0.5, 0, 255).astype(np.uint8)
    out = Image.fromarray(arr, "RGBa").convert("RGBA").resize((max(1, W2 // 2), max(1, H2 // 2)), Image.LANCZOS)
    return out, (X0, Y0, X1 - X0, Y1 - Y0)


def mascara_tecido_suave(im: Image.Image, topo: float, barra: float) -> np.ndarray:
    """Máscara 0..1 da camiseta em resolução cheia, com borda suave, para recolorir o tecido.

    Silhueta da pessoa, menos pele, entre a gola e a barra (as sombras das laterais entram, o que
    uma máscara só por cor perde). Perto da barra, onde começa a calça, decide pela cor do tecido.
    """
    from scipy import ndimage
    rgba = im.convert("RGBA")
    arr = np.asarray(rgba)
    H = arr.shape[0]
    pessoa = arr[..., 3] > 20
    pele = ndimage.binary_dilation(mascara_pele(arr[..., :3]), iterations=3)
    yy = np.arange(H)[:, None]
    geo = pessoa & ~pele & (yy >= topo - 40) & (yy <= barra + 40)
    # metade de baixo: cada pixel vai para o tecido ou para a calça, o que tiver a cor mais próxima
    base = mascara_camiseta(rgba)
    L = _lab(arr[..., :3].astype(np.float32))
    w = np.array([0.3, 1.5, 1.5])
    ref = np.median(L[base], axis=0)
    calca_zona = pessoa & ~pele & (yy > barra + 40) & (yy < barra + 160)
    ref_c = np.median(L[calca_zona], axis=0) if calca_zona.sum() > 200 else ref + 100
    d_s = np.linalg.norm((L - ref) * w, axis=-1)
    d_c = np.linalg.norm((L - ref_c) * w, axis=-1)
    pele_ref = np.median(L[mascara_pele(arr[..., :3]) & pessoa], axis=0)
    d_p = np.linalg.norm((L - pele_ref) * w, axis=-1)
    tecido = ndimage.median_filter((d_s < d_c).astype(np.uint8), 5).astype(bool)
    nao_pele = ndimage.median_filter((d_s < d_p).astype(np.uint8), 5).astype(bool)   # sombra de braço fica fora
    baixo = yy > topo + 0.45 * (barra - topo)
    m = geo & nao_pele & (~baixo | tecido)
    m = ndimage.binary_closing(ndimage.binary_opening(m, iterations=2), iterations=3)
    # só a peça ligada ao tronco (tira relógio, pedaços soltos)
    rot, n = ndimage.label(m)
    if n > 1:
        tam = ndimage.sum(m, rot, range(1, n + 1))
        m = rot == (1 + int(np.argmax(tam)))
    m = ndimage.binary_fill_holes(m)
    mf = ndimage.gaussian_filter(m.astype(np.float32), 1.2) * (arr[..., 3] / 255.0)
    return mf


def recolorir_camiseta(mk: "MockupPreparado", cor_alvo: Tuple[int, int, int], mascara: np.ndarray) -> None:
    """Troca a cor do tecido pela cor do mockup, mantendo luz, sombra e trama da foto.

    Ganho por canal em luz linear (cor alvo / cor medida do tecido): cada pixel da camiseta é
    multiplicado por ele, então dobras e textura continuam iguais, só o tom muda.
    """
    from imagem import srgb_para_linear, linear_para_srgb
    lin = srgb_para_linear(mk.rgb.astype(np.float32) / 255.0)
    pesos = mascara > 0.8
    atual = np.median(lin[pesos], axis=0)
    alvo = srgb_para_linear(np.array(cor_alvo, np.float32) / 255.0)
    ganho = alvo / np.maximum(atual, 1e-4)
    novo = np.clip(lin * ganho, 0, 1)
    out = lin * (1 - mascara[..., None]) + novo * mascara[..., None]
    mk.rgb = np.clip(linear_para_srgb(out) * 255 + 0.5, 0, 255).astype(np.uint8)
    mk.rgb_tecido = tuple(int(v) for v in np.median(mk.rgb[pesos], axis=0))
    mk.imagem = Image.fromarray(mk.rgb, "RGB").convert("RGBA")
    mk.imagem.putalpha(Image.fromarray(mk.alpha))
