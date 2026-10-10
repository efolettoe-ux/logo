"""Motor v3 (OpenCV): leva a estampa do mockup liso para a foto do modelo.

Ideia: o mockup liso já tem a estampa na posição e na escala certas. Em vez de medir a posição de
novo em cada foto, o motor acha os mesmos pontos da camiseta (ombros, axilas, laterais, barra,
linha da gola) no mockup e na foto e deforma a camada da estampa de um para o outro:

1. geometria: pontos de referência + modelo de cilindro do tronco -> transformação "thin plate
   spline" (TPS). Ela cuida de posição, escala, perspectiva, inclinação e curvatura de uma vez;
2. dobras: deslocamento pelo gradiente das dobras (média zero), não pelo brilho absoluto;
3. luz: tinta = cor da arte x iluminação do tecido (foto / cor do tecido), igual para todas as cores;
4. textura: trama com amplitude fixa (não relativa), igual em camiseta clara e escura;
5. oclusão: braço/mão (pele) por cima da estampa.

Nada é gerado por IA; a foto e a arte originais não são alteradas.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import cv2
import numpy as np


# --------------------------------------------------------------------------------------------
# 1. Pontos de referência da camiseta (mesmo método no mockup liso e na foto)
# --------------------------------------------------------------------------------------------

NOMES = ("ombro_e", "ombro_d", "axila_e", "axila_d", "lado_e", "lado_d", "barra_e", "barra_d",
         "barra_c", "gola")


@dataclass
class Pontos:
    p: Dict[str, Tuple[float, float]]
    cx: float           # centro do tronco (meio das laterais) na altura do peito
    raio: float         # meia largura do tronco
    gola_x: float       # linha do esterno/coluna

    def matriz(self) -> np.ndarray:
        return np.array([self.p[n] for n in NOMES], np.float32)


def _contorno(mask: np.ndarray) -> np.ndarray:
    m = (mask > 0).astype(np.uint8) * 255
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(cs, key=cv2.contourArea)
    return c[:, 0, :]


def _borda_x(mask: np.ndarray, y: int, x_ref: float, lado: int) -> float:
    """x da borda do tecido na linha y, andando a partir de x_ref para a esquerda (-1) ou direita (+1)."""
    linha = mask[int(y)] > 0
    x = int(round(x_ref))
    if not linha[x]:
        idx = np.nonzero(linha)[0]
        x = int(idx[np.argmin(np.abs(idx - x))])
    while 0 < x < len(linha) - 1 and linha[x + lado]:
        x += lado
    return float(x)


def _topo_y(mask: np.ndarray, x: float) -> float:
    col = np.nonzero(mask[:, int(round(x))] > 0)[0]
    return float(col.min())


def _fundo_y(mask: np.ndarray, x: float) -> float:
    col = np.nonzero(mask[:, int(round(x))] > 0)[0]
    return float(col.max())


def achar_pontos(mask: np.ndarray, gola_x: Optional[float] = None,
                 r_axila: Optional[float] = None) -> Pontos:
    """Ombros, axilas, laterais, barra e linha da gola a partir da máscara da camiseta (com mangas).

    Axilas = as duas concavidades mais fundas do contorno (entre manga e tronco), achadas pelos
    defeitos de convexidade do OpenCV. Na foto com o braço para baixo essa concavidade fica na
    barra da manga, abaixo da axila de verdade; por isso, se ``r_axila`` vier (a proporção
    ombro->axila->barra medida no mockup liso), a altura da axila vem dela e o x da lateral do
    tronco naquela altura.
    """
    c = _contorno(mask)
    ys = c[:, 1]
    topo, base = float(ys.min()), float(ys.max())
    alt = base - topo
    hull = cv2.convexHull(c, returnPoints=False)
    defs = cv2.convexityDefects(c, hull)
    meio = float(np.median(c[:, 0]))
    axilas = []
    if defs is not None:
        for s, e, f, d in defs.reshape(-1, 4):
            x, y = c[f]
            if topo + 0.12 * alt < y < topo + 0.6 * alt:
                axilas.append((d, float(x), float(y)))
    esq = [a for a in axilas if a[1] < meio]
    dir_ = [a for a in axilas if a[1] >= meio]
    if not esq or not dir_:
        raise ValueError("não achei as duas axilas no contorno")
    _, axe, aye = max(esq)
    _, axd, ayd = max(dir_)
    # linha da barra: fundo do tronco entre as axilas
    xs_t = np.linspace(axe + 0.15 * (axd - axe), axd - 0.15 * (axd - axe), 15)
    y_barra = float(np.median([_fundo_y(mask, x) for x in xs_t]))
    meio_t = (axe + axd) / 2
    oe, od = (axe, _topo_y(mask, axe)), (axd, _topo_y(mask, axd))
    y_ombro = (oe[1] + od[1]) / 2
    if r_axila is not None:
        aye = oe[1] + r_axila * (y_barra - oe[1])
        ayd = od[1] + r_axila * (y_barra - od[1])
        axe, axd = _borda_x(mask, aye, meio_t, -1), _borda_x(mask, ayd, meio_t, +1)
    y_ax = (aye + ayd) / 2
    y_lado = y_ax + 0.5 * (y_barra - y_ax)
    le, ld = _borda_x(mask, y_lado, meio_t, -1), _borda_x(mask, y_lado, meio_t, +1)
    yb = y_barra - 0.04 * (y_barra - y_ax)
    be, bd = _borda_x(mask, yb, meio_t, -1), _borda_x(mask, yb, meio_t, +1)
    cx = (le + ld) / 2
    raio = (ld - le) / 2
    if gola_x is None:
        # linha da gola: meio do "vale" do pescoço no topo, entre os ombros
        xs = np.arange(int(axe + 0.25 * (axd - axe)), int(axd - 0.25 * (axd - axe)))
        tops = np.array([_topo_y(mask, x) for x in xs])
        fundo = tops >= np.percentile(tops, 80)
        gola_x = float(xs[fundo].mean())
    p = {
        "ombro_e": oe, "ombro_d": od,
        "axila_e": (axe, aye), "axila_d": (axd, ayd),
        "lado_e": (le, y_lado), "lado_d": (ld, y_lado),
        "barra_e": (be, yb), "barra_d": (bd, yb),
        "barra_c": (gola_x, _fundo_y(mask, gola_x)),
        "gola": (gola_x, y_ombro),
    }
    return Pontos(p, cx, raio, float(gola_x))


def proporcao_axila(pt: Pontos) -> float:
    """(axila - ombro) / (barra - ombro), média dos dois lados."""
    yb = (pt.p["barra_e"][1] + pt.p["barra_d"][1]) / 2
    r = [(pt.p[a][1] - pt.p[o][1]) / (yb - pt.p[o][1]) for a, o in (("axila_e", "ombro_e"), ("axila_d", "ombro_d"))]
    return float(np.mean(r))


# --------------------------------------------------------------------------------------------
# 2. Transformação mockup liso -> foto (TPS com pontos de cilindro no meio do tronco)
# --------------------------------------------------------------------------------------------

class Elipse:
    """Corte do tronco como elipse (meia largura 1, meia profundidade ``prof``).

    O tecido plano do mockup (fração f da meia largura, -1..1 = costura lateral a costura lateral)
    é enrolado nessa elipse preservando o comprimento do tecido; o corpo pode estar virado (giro).
    No meio das costas/peito o tecido fica quase de frente para a câmera, então a estampa aparece
    maior em relação à largura visível do tronco do que no mockup plano; perto das laterais encolhe.
    """

    def __init__(self, prof: float = 0.65, n: int = 2001):
        self.prof = prof
        t = np.linspace(-np.pi / 2, np.pi / 2, n)
        dx, dz = np.cos(t), -prof * np.sin(t)
        ds = np.hypot(dx, dz)
        s = np.concatenate([[0], np.cumsum((ds[1:] + ds[:-1]) / 2 * np.diff(t))])
        s -= s[n // 2]
        self.t, self.f, self.smax = t, s / s[-1], float(s[-1])

    def x_proj(self, f, giro: float):
        """x projetado (unidades da meia largura, já dividido pela meia largura visível) do ponto f."""
        t = np.interp(f, self.f, self.t)
        x = np.sin(t) * np.cos(giro) + self.prof * np.cos(t) * np.sin(giro)
        meia = np.sqrt(np.cos(giro) ** 2 + (self.prof * np.sin(giro)) ** 2)
        return x / meia

    def giro_da_gola(self, rel: float) -> float:
        """Giro do corpo a partir de onde a gola (f=0) aparece: rel = (gola_x - cx) / raio_visivel."""
        gs = np.linspace(-1.2, 1.2, 2401)
        v = np.array([float(self.x_proj(0.0, g)) for g in gs])
        return float(gs[np.argmin(np.abs(v - rel))])


_ELIPSE = Elipse()


def _pontos_corpo(pm: Pontos, pf: Pontos, linhas=(-0.35, 0.0, 0.33, 0.66, 1.0),
                  fracs=(-0.95, -0.8, -0.6, -0.4, -0.2, 0.2, 0.4, 0.6, 0.8, 0.95)):
    """Pares extras dentro do tronco: plano no mockup, enrolado na elipse (com giro) na foto."""
    src, dst = [], []
    giro = _ELIPSE.giro_da_gola((pf.gola_x - pf.cx) / pf.raio)
    ya_m = (pm.p["axila_e"][1] + pm.p["axila_d"][1]) / 2
    yb_m = (pm.p["barra_e"][1] + pm.p["barra_d"][1]) / 2
    ya_f = (pf.p["axila_e"][1] + pf.p["axila_d"][1]) / 2
    yb_f = (pf.p["barra_e"][1] + pf.p["barra_d"][1]) / 2
    for t in linhas:
        ym, yf = ya_m + t * (yb_m - ya_m), ya_f + t * (yb_f - ya_f)
        for f in fracs + (0.0,):
            src.append((pm.gola_x + f * pm.raio, ym))
            dst.append((pf.cx + pf.raio * float(_ELIPSE.x_proj(f, giro)), yf))
    return np.array(src, np.float32), np.array(dst, np.float32), giro


def _tps(src: np.ndarray, dst: np.ndarray, reg: float = 1.0):
    """Ajusta TPS dst->src (mapeamento inverso: para cada pixel da foto, onde ler no mockup)."""
    n = len(src)
    def U(r2):
        with np.errstate(divide="ignore", invalid="ignore"):
            v = r2 * np.log(r2)
        return np.nan_to_num(v)
    d2 = ((dst[:, None, :] - dst[None, :, :]) ** 2).sum(-1)
    K = U(d2) + reg * np.eye(n)
    P = np.hstack([np.ones((n, 1)), dst])
    A = np.zeros((n + 3, n + 3))
    A[:n, :n], A[:n, n:], A[n:, :n] = K, P, P.T
    b = np.zeros((n + 3, 2))
    b[:n] = src
    coef = np.linalg.solve(A, b)
    w, a = coef[:n], coef[n:]

    def aplicar(xy: np.ndarray) -> np.ndarray:
        r2 = ((xy[:, None, :] - dst[None, :, :]) ** 2).sum(-1)
        return U(r2) @ w + a[0] + xy @ a[1:]
    return aplicar


def levar_camada(camada: np.ndarray, pm: Pontos, pf: Pontos, tamanho_foto: Tuple[int, int],
                 caixa_foto: Tuple[int, int, int, int]) -> np.ndarray:
    """Deforma a camada RGBA (float 0..1, no espaço do mockup liso) para o espaço da foto.

    Só calcula dentro de caixa_foto (x0, y0, x1, y1) para ser rápido; fora dela fica transparente.
    """
    # verticais (ombro, gola, barra) vêm dos pontos; o horizontal do tronco vem da elipse
    usar = ("ombro_e", "ombro_d", "gola", "barra_c")
    s1 = np.array([pm.p[k] for k in usar], np.float32)
    d1 = np.array([pf.p[k] for k in usar], np.float32)
    s2, d2, _ = _pontos_corpo(pm, pf)
    src, dst = np.vstack([s1, s2]), np.vstack([d1, d2])
    f = _tps(src, dst)
    x0, y0, x1, y1 = caixa_foto
    W, H = tamanho_foto
    # malha grossa + interpolação (TPS é suave), depois remap em resolução cheia
    passo = 8
    gx = np.arange(x0, x1 + passo, passo, dtype=np.float32)
    gy = np.arange(y0, y1 + passo, passo, dtype=np.float32)
    XX, YY = np.meshgrid(gx, gy)
    m = f(np.stack([XX.ravel(), YY.ravel()], 1)).astype(np.float32)
    mx = cv2.resize(m[:, 0].reshape(XX.shape), (x1 - x0, y1 - y0), interpolation=cv2.INTER_CUBIC)
    my = cv2.resize(m[:, 1].reshape(XX.shape), (x1 - x0, y1 - y0), interpolation=cv2.INTER_CUBIC)
    # premultiplicado para não sujar a borda
    pre = camada.copy()
    pre[..., :3] *= pre[..., 3:4]
    out = np.zeros((H, W, 4), np.float32)
    out[y0:y1, x0:x1] = cv2.remap(pre, mx, my, cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT,
                                  borderValue=0)
    out = np.clip(out, 0, 1)
    return out


# --------------------------------------------------------------------------------------------
# 3. Dobras, luz e textura
# --------------------------------------------------------------------------------------------

def srgb_lin(a):
    return np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)


def lin_srgb(a):
    a = np.clip(a, 0, 1)
    return np.where(a <= 0.0031308, a * 12.92, 1.055 * a ** (1 / 2.4) - 0.055)


def compor(foto_rgb: np.ndarray, foto_a: np.ndarray, camisa: np.ndarray, pele: np.ndarray,
           camada: np.ndarray, cor_tecido: Tuple[float, float, float], dobra_px: float = 4.0,
           textura: float = 0.012, borda_px: float = 0.5) -> np.ndarray:
    """Aplica a camada (premultiplicada, já no espaço da foto) com dobras, luz e textura.

    foto_rgb: HxWx3 float 0..1 (sRGB). camisa/pele: HxW float 0..1.
    """
    ys, xs = np.nonzero(camada[..., 3] > 1e-3)
    if len(ys) == 0:
        return foto_rgb
    m = 24
    y0, y1 = max(0, ys.min() - m), min(foto_rgb.shape[0], ys.max() + m + 1)
    x0, x1 = max(0, xs.min() - m), min(foto_rgb.shape[1], xs.max() + m + 1)
    foto = foto_rgb[y0:y1, x0:x1]
    lin = srgb_lin(foto)
    lum = lin @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    tec = srgb_lin(np.array(cor_tecido, np.float32))
    lum_tec = float(tec @ np.array([0.2126, 0.7152, 0.0722], np.float32))
    # iluminação = foto / cor do tecido, sem a trama (filtro bilateral guarda a borda das dobras)
    ilum = lum / max(lum_tec, 1e-4)
    ilum32 = ilum.astype(np.float32)
    ruido = float(np.std(ilum32 - cv2.GaussianBlur(ilum32, (0, 0), 1.5))) + 1e-4
    # sigma de cor acima do ruído da trama: a trama some, a borda das dobras fica
    ilum_s = cv2.bilateralFilter(cv2.GaussianBlur(ilum32, (0, 0), 1.2), 11, 4 * ruido, 5)
    ilum_s = np.clip(ilum_s, 0.25, 1.6)
    # dobras: gradiente da sombra de média frequência (média zero) -> desloca a estampa
    banda = cv2.GaussianBlur(ilum_s, (0, 0), 3) - cv2.GaussianBlur(ilum_s, (0, 0), 30)
    gx = cv2.Sobel(banda, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(banda, cv2.CV_32F, 0, 1, ksize=3)
    norma = float(np.percentile(np.hypot(gx, gy), 99)) + 1e-6
    dx, dy = gx / norma * dobra_px, gy / norma * dobra_px
    H, W = lum.shape
    XX, YY = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
    cam = camada[y0:y1, x0:x1]
    cam = cv2.remap(cam, XX - dx, YY - dy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    a = cam[..., 3]
    cor = np.where(a[..., None] > 1e-4, cam[..., :3] / np.maximum(a[..., None], 1e-4), 0)
    # trama: amplitude fixa (não relativa ao brilho) -> igual em camiseta clara e escura
    trama = cv2.GaussianBlur(lum, (0, 0), 0.6) - cv2.GaussianBlur(lum, (0, 0), 2.0)
    trama = trama / (float(np.std(trama[camisa[y0:y1, x0:x1] > 0.5])) + 1e-6) * textura
    tinta = srgb_lin(cor) * ilum_s[..., None] * (1 + trama[..., None])
    # tinta mais fina nos poros + borda de tinta (não recorte)
    a = a * np.clip(1 - 0.025 * np.clip(-trama / max(textura, 1e-6), 0, 2), 0, 1)
    if borda_px > 0:
        a = cv2.GaussianBlur(a, (0, 0), borda_px)
    a = a * camisa[y0:y1, x0:x1] * (1 - pele[y0:y1, x0:x1])
    out_lin = lin * (1 - a[..., None]) + tinta * a[..., None]
    res = foto_rgb.copy()
    res[y0:y1, x0:x1] = lin_srgb(out_lin)
    return res


def mapa_corpo(pm: Pontos, pf: Pontos, caixa_foto: Tuple[int, int, int, int], y_ancora_m: Optional[float] = None,
               elipse: Elipse = _ELIPSE):
    """Mapa inverso foto -> mockup liso, sem esticar a arte:

    - horizontal: tecido plano enrolado na elipse do tronco (com o giro do corpo);
    - escala única k (px da foto por px do mockup) = ampliação no meio do tronco, usada também na
      vertical, então a arte não achata nem estica;
    - altura: o topo da arte (y_ancora_m no mockup) fica na mesma proporção do comprimento da
      camiseta (linha dos ombros -> barra) que no mockup; dali para baixo vale a escala k. Acompanha
      a inclinação dos ombros na foto.
    Retorna (mapa_x, mapa_y, k, giro).
    """
    giro = elipse.giro_da_gola((pf.gola_x - pf.cx) / pf.raio)
    fs = np.linspace(-0.98, 0.98, 1961)
    xs = pf.cx + pf.raio * elipse.x_proj(fs, giro)
    ordem = np.argsort(xs)
    xs, fs = xs[ordem], fs[ordem]
    # ampliação no centro da arte (perto da gola): d(x_foto)/d(x_mockup)
    i0 = np.argmin(np.abs(fs))
    k = float((xs[min(i0 + 5, len(xs) - 1)] - xs[max(i0 - 5, 0)]) / ((fs[min(i0 + 5, len(fs) - 1)] - fs[max(i0 - 5, 0)]) * pm.raio))
    x0, y0, x1, y1 = caixa_foto
    X, Y = np.meshgrid(np.arange(x0, x1, dtype=np.float32), np.arange(y0, y1, dtype=np.float32))
    f = np.interp(X, xs, fs, left=np.nan, right=np.nan)
    mx = pm.gola_x + f * pm.raio
    (oex, oey), (odx, ody) = pf.p["ombro_e"], pf.p["ombro_d"]
    inclin = (ody - oey) / max(odx - oex, 1.0)
    y_ombro_f = pf.p["gola"][1] + inclin * (X - pf.p["gola"][0])
    y_ombro_m = pm.p["gola"][1]
    if y_ancora_m is None:
        y_ancora_m = y_ombro_m
    comp_m = pm.p["barra_c"][1] - y_ombro_m
    comp_f = pf.p["barra_c"][1] - pf.p["gola"][1]
    y_ancora_f = y_ombro_f + (y_ancora_m - y_ombro_m) * comp_f / comp_m
    my = y_ancora_m + (Y - y_ancora_f) / k
    mx = np.where(np.isnan(mx), -1e4, mx).astype(np.float32)
    return mx, my.astype(np.float32), k, giro


def levar_camada_corpo(camada: np.ndarray, pm: Pontos, pf: Pontos, tamanho_foto: Tuple[int, int],
                       caixa_foto: Tuple[int, int, int, int], y_ancora_m: Optional[float] = None) -> np.ndarray:
    mx, my, k, giro = mapa_corpo(pm, pf, caixa_foto, y_ancora_m)
    W, H = tamanho_foto
    x0, y0, x1, y1 = caixa_foto
    pre = camada.copy()
    pre[..., :3] *= pre[..., 3:4]
    # a arte vai ficar menor (k<1): suaviza antes para não serrilhar
    if k < 0.9:
        pre = cv2.GaussianBlur(pre, (0, 0), 0.45 / max(k, 0.05))
    out = np.zeros((H, W, 4), np.float32)
    out[y0:y1, x0:x1] = cv2.remap(pre, mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT,
                                  borderValue=0)
    return np.clip(out, 0, 1)



def mapa_corpo_v2(pm: Pontos, pf: Pontos, caixa_foto: Tuple[int, int, int, int], ancora_m: Tuple[float, float],
                  elipse: Elipse = _ELIPSE):
    """Mapa inverso foto -> mockup liso com duas escalas separadas:

    - POSIÇÃO (onde fica o centro/topo da arte): proporcional ao comprimento da camiseta
      (ombros -> barra), igual ao mockup: kv = comprimento na foto / comprimento no mockup.
      O deslocamento lateral vira arco no tecido do tronco (elipse, com giro).
    - TAMANHO da arte: escala k do meio do tronco (tecido de frente para a câmera), igual na
      horizontal e na vertical; a arte enrola na elipse a partir da âncora.
    ancora_m = (x do centro da arte, y do topo da arte) no mockup liso.
    """
    giro = elipse.giro_da_gola((pf.gola_x - pf.cx) / pf.raio)
    R = pf.raio
    ts = elipse.t
    meia = np.sqrt(np.cos(giro) ** 2 + (elipse.prof * np.sin(giro)) ** 2)
    xs = pf.cx + R * (np.sin(ts) * np.cos(giro) + elipse.prof * np.cos(ts) * np.sin(giro)) / meia
    arcos = R * elipse.f * elipse.smax / meia          # arco do tecido (px da foto) a partir de t=0
    comp_m = pm.p["barra_c"][1] - pm.p["gola"][1]
    comp_f = pf.p["barra_c"][1] - pf.p["gola"][1]
    kv = comp_f / comp_m
    # escala k (tamanho): a meia largura do mockup plano = meio perímetro do tronco na foto
    k = float((R / meia) * elipse.smax / pm.raio)
    # âncora: arco lateral pela escala da posição (kv)
    xa_m, ya_m = ancora_m
    arco_ancora = kv * (xa_m - pm.gola_x)
    x0, y0, x1, y1 = caixa_foto
    X, Y = np.meshgrid(np.arange(x0, x1, dtype=np.float32), np.arange(y0, y1, dtype=np.float32))
    ordem = np.argsort(xs)
    arco_x = np.interp(X, xs[ordem], arcos[ordem], left=np.nan, right=np.nan)
    mx = xa_m + (arco_x - arco_ancora) / k
    (oex, oey), (odx, ody) = pf.p["ombro_e"], pf.p["ombro_d"]
    inclin = (ody - oey) / max(odx - oex, 1.0)
    y_ombro_f = pf.p["gola"][1] + inclin * (X - pf.p["gola"][0])
    y_ancora_f = y_ombro_f + (ya_m - pm.p["gola"][1]) * kv
    my = ya_m + (Y - y_ancora_f) / k
    mx = np.where(np.isnan(mx), -1e4, mx).astype(np.float32)
    return mx, my.astype(np.float32), k, kv, giro


def levar_camada_corpo_v2(camada: np.ndarray, pm: Pontos, pf: Pontos, tamanho_foto: Tuple[int, int],
                          caixa_foto: Tuple[int, int, int, int], ancora_m: Tuple[float, float]) -> np.ndarray:
    mx, my, k, kv, giro = mapa_corpo_v2(pm, pf, caixa_foto, ancora_m)
    W, H = tamanho_foto
    x0, y0, x1, y1 = caixa_foto
    pre = camada.copy()
    pre[..., :3] *= pre[..., 3:4]
    if k < 0.9:
        pre = cv2.GaussianBlur(pre, (0, 0), 0.45 / max(k, 0.05))
    out = np.zeros((H, W, 4), np.float32)
    out[y0:y1, x0:x1] = cv2.remap(pre, mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return np.clip(out, 0, 1)
