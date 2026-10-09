"""Geradores de imagens sintéticas para os testes (camiseta lisa, foto da loja, estampa)."""
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

FUNDO_LOJA = (237, 237, 237)


def poligono_camiseta(W, H):
    """Silhueta de camiseta (manga curta) ocupando ~60% do quadro."""
    cx = W / 2
    corpo = 0.22 * W
    return [(cx - 0.06 * W, 0.20 * H), (cx - corpo, 0.24 * H), (cx - 0.40 * W, 0.40 * H), (cx - 0.33 * W, 0.50 * H),
            (cx - corpo, 0.44 * H), (cx - corpo, 0.80 * H), (cx + corpo, 0.80 * H), (cx + corpo, 0.44 * H),
            (cx + 0.33 * W, 0.50 * H), (cx + 0.40 * W, 0.40 * H), (cx + corpo, 0.24 * H), (cx + 0.06 * W, 0.20 * H),
            (cx, 0.23 * H)]


def mockup_liso(W=600, H=800, cor=(20, 20, 22), seed=1):
    """Camiseta lisa RGBA com fundo transparente, dobras suaves e textura fina."""
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).polygon(poligono_camiseta(W, H), fill=255)
    m = m.filter(ImageFilter.GaussianBlur(0.7))
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    amp = 0.10 if max(cor) < 128 else 0.012  # tecido claro: dobras sutis (como nas fotos reais)
    dobra = 1.0 + amp * np.sin(xx / W * 9.0 + yy / H * 3.0) + amp * 0.2 * rng.standard_normal((H, W))
    base = np.array(cor, np.float32)[None, None, :] * dobra[..., None]
    if max(cor) < 80:
        base = base + 6 * (dobra[..., None] - 1.0) * 10
    rgb = np.clip(base, 0, 255).astype(np.uint8)
    return Image.fromarray(np.dstack([rgb, np.asarray(m)]), "RGBA")


def estampa(W=200, H=260, cor=(200, 30, 40)):
    """Arte RGBA: retângulo arredondado colorido com miolo branco (sem fundo)."""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=W // 8, fill=cor + (255,))
    d.ellipse([W * 0.25, H * 0.25, W * 0.75, H * 0.75], fill=(255, 255, 255, 255))
    return im


def foto_loja(cor=(23, 23, 22), estampa_caixa=None, lado=800, borda_escura=True):
    """'Foto da loja': camiseta opaca sobre o cinza claro, contorno levemente escuro, estampa opcional."""
    W = H = lado
    fundo = Image.new("RGB", (W, H), FUNDO_LOJA)
    mk = mockup_liso(W, H, cor)
    if borda_escura:
        a = mk.getchannel("A")
        contorno = a.filter(ImageFilter.MaxFilter(3))
        sombra = Image.new("RGB", (W, H), (200, 200, 200))
        fundo.paste(sombra, (0, 0), contorno)
    fundo.paste(mk.convert("RGB"), (0, 0), mk.getchannel("A"))
    if estampa_caixa:
        x0, y0, x1, y1 = estampa_caixa
        art = estampa(int(x1 - x0), int(y1 - y0))
        fundo.paste(art.convert("RGB"), (int(x0), int(y0)), art.getchannel("A"))
    return fundo
