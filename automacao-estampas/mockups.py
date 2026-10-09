"""Mockups lisos: descobrir os arquivos (cor + vista) e alinhar o close das costas com as costas.

Vistas: "frente", "costas", "close-costas" (detalhe ampliado da parte de cima das costas) e
"costas-inclinada" (as costas giradas no quadro; a estampa acompanha a inclinação).
A cor e a vista vêm do nome do arquivo (ex.: "off-white-close-costas.png"); config.json pode forçar.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

from catalogo import ErroUsuario, _colapsar, chave_cor, tabela_cores, tokens
from imagem import EXT_IMAGEM, carregar_imagem, desfocar, srgb_para_linear

VISTAS = ("costas", "frente", "close-costas", "costas-inclinada")
PALAVRAS_INCLINADA = {"costas-inclinada": ["costas inclinada", "inclinada", "inclinado", "diagonal"]}


@dataclass
class Mockup:
    cor: str
    vista: str
    caminho: Path


@dataclass
class ResultadoMockups:
    pasta: Optional[Path]
    mockups: Dict[Tuple[str, str], Mockup]   # (cor, vista) -> Mockup
    ignorados: List[Tuple[Path, str]]        # arquivo + motivo
    cores_desativadas: List[str]

    def tem(self, cor: str, vista: str) -> bool:
        return (cor, vista) in self.mockups

    def caminho(self, cor: str, vista: str) -> Optional[Path]:
        m = self.mockups.get((cor, vista))
        return m.caminho if m else None

    def cores_completas(self) -> set:
        """Cores com frente E costas (o mínimo para gerar um produto)."""
        cores = {c for c, _ in self.mockups}
        return {c for c in cores if (c, "frente") in self.mockups and (c, "costas") in self.mockups}


def _pistas_mockup(nome_arquivo: str, cfg: dict) -> Tuple[Optional[str], Optional[str]]:
    """'azul-marinho-close-costas.png' -> ('Azul Marinho', 'close-costas')."""
    tks = [_colapsar(t) for t in tokens(Path(nome_arquivo).stem)]
    texto = " " + " ".join(tks) + " "
    vista = None
    pv = dict(PALAVRAS_INCLINADA, **cfg["mockups"]["palavras_vista"])
    for v in ("costas-inclinada", "close-costas", "frente", "costas"):  # as compostas primeiro (contêm "costas")
        for p in pv.get(v, []):
            if " " + " ".join(_colapsar(x) for x in chave_cor(p).split()) + " " in texto:
                vista = v
                break
        if vista:
            break
    cor = None
    pares = []
    for c in tabela_cores(cfg):
        for a in [chave_cor(c.nome), chave_cor(c.codigo)] + c.apelidos:
            if a and len(a) >= 2:
                pares.append((" " + " ".join(_colapsar(x) for x in a.split()) + " ", c.nome))
    pares.sort(key=lambda p: -len(p[0]))
    for a, nome in pares:
        if a in texto:
            cor = nome
            break
    return cor, vista


def achar_pasta_mockups(raiz: Path, cfg: dict, tipo: str = "camiseta", informada: Optional[str] = None) -> Optional[Path]:
    if informada:
        p = Path(informada).expanduser()
        p = p if p.is_absolute() else raiz / p
        if not p.is_dir():
            raise ErroUsuario(f"A pasta de mockups informada não existe: {p}")
        return p
    cand = cfg["tipos"][tipo].get("pasta_mockups", [])
    if isinstance(cand, str):
        cand = [cand]
    # procura na pasta do projeto, na pasta das artes (casar.pasta_arquivos) e na pasta de cima
    bases = [raiz]
    pa = str(cfg.get("casar", {}).get("pasta_arquivos", "") or "").strip()
    if pa:
        bases.append(Path(pa).expanduser())
    bases.append(raiz.parent)
    for base in bases:
        for c in cand:
            p = base / c
            if p.is_dir():
                return p
    return None


def descobrir_mockups(pasta: Optional[Path], cfg: dict) -> ResultadoMockups:
    """Lista os mockups da pasta. Cores com "ativa": false (ex.: Chumbo) ficam de fora por enquanto."""
    ativas = {c.nome: c.ativa for c in tabela_cores(cfg)}
    res = ResultadoMockups(pasta, {}, [], [])
    if pasta is None or not Path(pasta).is_dir():
        return res
    explicitos = {k.lower(): v for k, v in cfg["mockups"].get("explicitos", {}).items()}
    desativadas = set()
    for arq in sorted(Path(pasta).iterdir()):
        if arq.name.startswith(".") or not arq.is_file():
            continue
        if arq.suffix.lower() not in EXT_IMAGEM:
            res.ignorados.append((arq, "não é imagem"))
            continue
        ex = explicitos.get(arq.name.lower())
        if ex:
            cor, vista = ex.get("cor"), ex.get("vista") or ex.get("lado")
            from catalogo import normalizar_cor
            cor = normalizar_cor(cor or "", cfg)[0] if cor else None
        else:
            cor, vista = _pistas_mockup(arq.name, cfg)
        if not cor or not vista:
            res.ignorados.append((arq, "nome sem cor ou sem vista (frente/costas/close-costas)"))
            continue
        if not ativas.get(cor, True):
            desativadas.add(cor)
            res.ignorados.append((arq, f"cor {cor} desativada no config.json"))
            continue
        chave = (cor, vista)
        if chave in res.mockups:
            res.ignorados.append((arq, f"repetido: já existe {res.mockups[chave].caminho.name}"))
            continue
        res.mockups[chave] = Mockup(cor, vista, arq)
    res.cores_desativadas = sorted(desativadas)
    return res


# ---------------------------------------------------------------------------
# Registro close-costas -> costas
# ---------------------------------------------------------------------------

@dataclass
class Registro:
    """Um ponto (x, y) das costas vai para ((x - tx) * escala, (y - ty) * escala) no close."""
    escala: float
    tx: float
    ty: float
    nota: float  # correlação (0-1); abaixo de ~0.5 desconfie

    def costas_para_close(self, x: float, y: float) -> Tuple[float, float]:
        return (x - self.tx) * self.escala, (y - self.ty) * self.escala

    def para_dict(self) -> dict:
        return {"escala": self.escala, "tx": self.tx, "ty": self.ty, "nota": self.nota}


def _assinatura(im: Image.Image, lado: int) -> Tuple[np.ndarray, float]:
    """Imagem de trabalho: luminância (sRGB) sobre cinza médio, reduzida para 'lado' px de largura."""
    s = lado / float(im.size[0])
    peq = im.resize((lado, max(1, round(im.size[1] * s))), Image.BOX)
    a = np.asarray(peq.convert("RGBA")).astype(np.float32) / 255.0
    lum = a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722
    al = a[..., 3]
    return lum * al + 0.5 * (1 - al), s


def _ncc_fft(img: np.ndarray, tpl: np.ndarray) -> np.ndarray:
    """Correlação cruzada normalizada (válida) de tpl dentro de img, via FFT."""
    H, W = img.shape
    h, w = tpl.shape
    if h > H or w > W:
        return np.full((1, 1), -1.0)
    t = tpl - tpl.mean()
    tn = np.sqrt((t * t).sum()) + 1e-9
    fs = (H + h, W + w)
    F = np.fft.rfft2(img, fs)
    T = np.fft.rfft2(t[::-1, ::-1], fs)
    corr = np.fft.irfft2(F * T, fs)[h - 1:H, w - 1:W]
    c1 = np.cumsum(np.cumsum(np.pad(img, ((1, 0), (1, 0))), 0), 1)
    c2 = np.cumsum(np.cumsum(np.pad(img * img, ((1, 0), (1, 0))), 0), 1)

    def soma(c):
        return c[h:, w:] - c[:-h, w:] - c[h:, :-w] + c[:-h, :-w]

    n = h * w
    s1 = soma(c1)
    var = np.maximum(soma(c2) - s1 * s1 / n, 1e-9)
    return corr / (tn * np.sqrt(var))


def registrar_close(costas: Image.Image, close: Image.Image, escalas: Optional[List[float]] = None) -> Registro:
    """Acha escala e posição do close dentro da imagem das costas (busca grossa + refino).

    Usa as bordas da peça (gola, ombros) e o sombreamento. Funciona para qualquer cor porque
    normaliza o contraste (correlação normalizada).
    """
    def prep(a):
        a = a - desfocar(a, 6.0)          # tira a luz geral, fica com contornos/dobras
        return a / (a.std() + 1e-6)

    base_lado = 360
    A, sa = _assinatura(costas, base_lado)
    A = prep(A)
    melhor = (-2.0, 1.0, 0.0, 0.0)
    if escalas is None:
        escalas = list(np.geomspace(1.05, 4.0, 40))
    Bfull = None
    for esc in escalas:
        # o close mostra (largura_close / esc) px das costas
        lado_tpl = int(round(close.size[0] / esc * sa))
        if lado_tpl < 40 or lado_tpl > A.shape[1]:
            continue
        B, _ = _assinatura(close, lado_tpl)
        if B.shape[0] > A.shape[0]:
            # close mais alto que as costas nessa escala: usa só o topo do close
            B = B[:A.shape[0] - 1]
        B = prep(B)
        r = _ncc_fft(A, B)
        i = np.unravel_index(int(np.argmax(r)), r.shape)
        v = float(r[i])
        if v > melhor[0]:
            melhor = (v, esc, i[1] / sa, i[0] / sa)
    nota, esc, tx, ty = melhor
    # refino: escala fina em volta da melhor, em resolução maior
    base_lado = 720
    A, sa = _assinatura(costas, base_lado)
    A = prep(A)
    for esc2 in np.linspace(esc * 0.96, esc * 1.04, 17):
        lado_tpl = int(round(close.size[0] / esc2 * sa))
        if lado_tpl < 40 or lado_tpl > A.shape[1]:
            continue
        B, _ = _assinatura(close, lado_tpl)
        if B.shape[0] > A.shape[0]:
            B = B[:A.shape[0] - 1]
        B = prep(B)
        r = _ncc_fft(A, B)
        i = np.unravel_index(int(np.argmax(r)), r.shape)
        v = float(r[i])
        if v >= nota:
            nota, esc, tx, ty = v, float(esc2), i[1] / sa, i[0] / sa
    # refino final quase na resolução cheia (meio pixel importa: o close amplia ~2x)
    base_lado = min(1400, costas.size[0])
    A, sa = _assinatura(costas, base_lado)
    A = prep(A)
    fino = None
    for esc2 in np.linspace(esc * 0.992, esc * 1.008, 9):
        lado_tpl = int(round(close.size[0] / esc2 * sa))
        if lado_tpl < 40 or lado_tpl > A.shape[1]:
            continue
        B, _ = _assinatura(close, lado_tpl)
        if B.shape[0] > A.shape[0]:
            B = B[:A.shape[0] - 1]
        B = prep(B)
        # só procura perto da posição já achada (recorte de A), bem mais rápido
        m = int(0.03 * A.shape[1]) + 4
        x0 = max(0, int(tx * sa) - m)
        y0 = max(0, int(ty * sa) - m)
        sub = A[y0:y0 + B.shape[0] + 2 * m, x0:x0 + B.shape[1] + 2 * m]
        r = _ncc_fft(sub, B)
        i = np.unravel_index(int(np.argmax(r)), r.shape)
        v = float(r[i])
        if fino is None or v > fino[0]:
            # sub-pixel: parábola em volta do máximo
            yy, xx = i
            dx = dy = 0.0
            if 0 < xx < r.shape[1] - 1:
                a_, b_, c_ = r[yy, xx - 1], r[yy, xx], r[yy, xx + 1]
                den = a_ - 2 * b_ + c_
                dx = 0.5 * (a_ - c_) / den if abs(den) > 1e-9 else 0.0
            if 0 < yy < r.shape[0] - 1:
                a_, b_, c_ = r[yy - 1, xx], r[yy, xx], r[yy + 1, xx]
                den = a_ - 2 * b_ + c_
                dy = 0.5 * (a_ - c_) / den if abs(den) > 1e-9 else 0.0
            fino = (v, float(esc2), (x0 + xx + dx) / sa, (y0 + yy + dy) / sa)
    if fino is not None:
        _, esc, tx, ty = fino
    # escala real: px do close por px das costas
    return Registro(round(float(esc), 5), round(float(tx), 2), round(float(ty), 2), round(float(nota), 4))


def _impressao(caminho: Path) -> str:
    st = caminho.stat()
    return hashlib.sha1(f"{caminho.name}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:16]


def registro_em_cache(costas: Path, close: Path, cache_json: Path, manual: Optional[dict] = None) -> Registro:
    """Registro close->costas guardado em cache (só recalcula se um dos arquivos mudar)."""
    if manual:
        return Registro(float(manual["escala"]), float(manual["tx"]), float(manual["ty"]), 1.0)
    chave = f"{costas.name}|{close.name}|{_impressao(costas)}|{_impressao(close)}"
    dados = {}
    if cache_json.exists():
        try:
            dados = json.loads(cache_json.read_text(encoding="utf-8"))
        except Exception:
            dados = {}
    if chave in dados:
        d = dados[chave]
        return Registro(d["escala"], d["tx"], d["ty"], d["nota"])
    reg = registrar_close(carregar_imagem(costas), carregar_imagem(close))
    dados[chave] = reg.para_dict()
    try:
        cache_json.parent.mkdir(parents=True, exist_ok=True)
        cache_json.write_text(json.dumps(dados, indent=1), encoding="utf-8")
    except OSError:
        pass
    return reg


# ---------------------------------------------------------------------------------------------
# Registro costas -> costas-inclinada (giro + escala + deslocamento, pelo contorno da peça)
# ---------------------------------------------------------------------------------------------
@dataclass
class RegistroInclinado:
    """Leva um ponto das costas retas (px do arquivo) para a foto inclinada (px do arquivo).

    Na foto inclinada a peça está girada e um pouco em perspectiva (corpo mais largo e mais curto, barra
    torta). Por isso o mapeamento é feito no quadro "desgirado": a altura é proporcional a partir da gola
    e, em cada altura, a posição horizontal é proporcional entre as duas laterais reais do corpo.
    """
    angulo: float            # giro costas -> inclinada (graus; PIL gira anti-horário com valor positivo)
    c_x0: float              # tronco das costas retas (px do arquivo)
    c_largura: float
    c_topo: float
    c_altura: float
    u_topo: float            # tronco no quadro desgirado (px reduzidos)
    u_altura: float
    esq: Tuple[float, float]  # lateral esquerda do corpo: x = a*y + b (quadro desgirado)
    dir: Tuple[float, float]
    centro_u: Tuple[float, float]  # centro do quadro desgirado
    centro_i: Tuple[float, float]  # centro da imagem inclinada reduzida
    k: float                 # px reduzidos por px do arquivo inclinado
    nota: float

    def ponto(self, x: float, y: float) -> Tuple[float, float]:
        v = (y - self.c_topo) / self.c_altura
        u = (x - self.c_x0) / self.c_largura
        yu = self.u_topo + v * self.u_altura
        xl = self.esq[0] * yu + self.esq[1]
        xr = self.dir[0] * yu + self.dir[1]
        xu = xl + u * (xr - xl)
        t = np.radians(self.angulo)
        c, s = np.cos(t), np.sin(t)
        dx, dy = xu - self.centro_u[0], yu - self.centro_u[1]
        # desgirado -> inclinada: gira de volta (mesma convenção do PIL)
        xi = self.centro_i[0] + c * dx - s * dy
        yi = self.centro_i[1] + s * dx + c * dy
        return xi / self.k, yi / self.k

    def para_dict(self) -> dict:
        d = {}
        for f in self.__dataclass_fields__:
            v = getattr(self, f)
            d[f] = [float(x) for x in v] if isinstance(v, tuple) else float(v)
        return d

    @classmethod
    def de_dict(cls, d: dict) -> "RegistroInclinado":
        return cls(**{k: (tuple(v) if isinstance(v, list) else v) for k, v in d.items()})


def _mascara_peca(im: Image.Image, lado: int) -> Tuple[np.ndarray, float]:
    k = lado / float(max(im.size))
    p = im.convert("RGBA").resize((max(1, round(im.size[0] * k)), max(1, round(im.size[1] * k))), Image.BILINEAR)
    a = np.asarray(p.getchannel("A")) > 128
    if a.all():  # sem transparência: separa do fundo claro pela cor do canto
        rgb = np.asarray(p.convert("RGB")).astype(np.int16)
        a = np.abs(rgb - rgb[2, 2]).sum(2) > 30
    return a, k


def _angulo_por_contorno(A: np.ndarray, B: np.ndarray) -> Tuple[float, float]:
    """Giro que melhor encaixa o contorno A (reto) no B (inclinado). Retorna (graus, IoU)."""
    ya, xa = np.nonzero(A)
    yb, xb = np.nonzero(B)
    ac = (xa.mean(), ya.mean())
    bc = (xb.mean(), yb.mean())
    s0 = np.sqrt(B.sum() / max(A.sum(), 1))
    imA = Image.fromarray((A * 255).astype(np.uint8))
    Hb, Wb = B.shape

    def iou(ang, esc):
        t = np.radians(ang)
        c, s = np.cos(t), np.sin(t)
        m = [c / esc, s / esc, 0.0, -s / esc, c / esc, 0.0]
        m[2] = ac[0] - (m[0] * bc[0] + m[1] * bc[1])
        m[5] = ac[1] - (m[3] * bc[0] + m[4] * bc[1])
        R = np.asarray(imA.transform((Wb, Hb), Image.AFFINE, m, Image.BILINEAR)) > 128
        return (R & B).sum() / max((R | B).sum(), 1)

    nota, ang, esc = max((iou(a, s0 * f), a, s0 * f) for a in range(-60, 61, 3) for f in (0.94, 1.0, 1.06))
    for passo in (1.0, 0.4, 0.15):
        for _ in range(20):
            cand = max((iou(ang + d, esc), ang + d) for d in (-passo, 0.0, passo))
            if cand[1] == ang:
                break
            nota, ang = cand
    return ang, nota


def registrar_inclinada(costas: Image.Image, incl: Image.Image) -> RegistroInclinado:
    from imagem import medir_torso
    A, ka = _mascara_peca(costas, 360)
    B, kb = _mascara_peca(incl, 360)
    ang, nota = _angulo_por_contorno(A, B)
    # tronco das costas retas
    A, ka = _mascara_peca(costas, 900)
    tc = medir_torso(A, ka, costas.size)
    # inclinada desgirada: o giro costas->inclinada foi "ang" na convenção do mapeamento; o PIL
    # desfaz com rotate(ang)
    B, kb = _mascara_peca(incl, 900)
    imB = Image.fromarray((B * 255).astype(np.uint8))
    up = imB.rotate(ang, resample=Image.BILINEAR, expand=True)
    U = np.asarray(up) > 128
    tu = medir_torso(U, 1.0)
    # laterais do corpo (abaixo da axila): reta x = a*y + b de cada lado
    ys = np.arange(int(tu.axila + 0.08 * tu.altura), int(tu.base - 0.06 * tu.altura))
    ys = ys[U[ys].any(axis=1)]
    xe = np.argmax(U[ys], axis=1).astype(float)
    xd = (U.shape[1] - 1 - np.argmax(U[ys, ::-1], axis=1)).astype(float)
    esq = tuple(np.polyfit(ys, xe, 1))
    dirr = tuple(np.polyfit(ys, xd, 1))
    return RegistroInclinado(
        angulo=float(ang), c_x0=tc.x0, c_largura=tc.largura, c_topo=tc.topo, c_altura=tc.base - tc.topo,
        u_topo=tu.topo, u_altura=tu.base - tu.topo, esq=(float(esq[0]), float(esq[1])),
        dir=(float(dirr[0]), float(dirr[1])), centro_u=(up.size[0] / 2.0, up.size[1] / 2.0),
        centro_i=(imB.size[0] / 2.0, imB.size[1] / 2.0), k=kb, nota=float(nota))


def registro_inclinada_em_cache(costas: Path, incl: Path, cache_json: Path,
                                manual: Optional[dict] = None) -> RegistroInclinado:
    if manual:
        return RegistroInclinado.de_dict(manual)
    chave = f"incl2|{costas.name}|{incl.name}|{_impressao(costas)}|{_impressao(incl)}"
    dados = {}
    if cache_json.exists():
        try:
            dados = json.loads(cache_json.read_text(encoding="utf-8"))
        except Exception:
            dados = {}
    if chave in dados:
        return RegistroInclinado.de_dict(dados[chave])
    reg = registrar_inclinada(carregar_imagem(costas), carregar_imagem(incl))
    dados[chave] = reg.para_dict()
    try:
        cache_json.parent.mkdir(parents=True, exist_ok=True)
        cache_json.write_text(json.dumps(dados, indent=1), encoding="utf-8")
    except OSError:
        pass
    return reg
