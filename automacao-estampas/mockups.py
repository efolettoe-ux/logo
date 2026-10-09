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
    """Ponto (x, y) das costas retas (px do arquivo) -> ponto na foto inclinada (px do arquivo)."""
    angulo: float      # graus (sentido da matriz abaixo, com y para baixo)
    escala: float
    ax: float          # centro da peça nas costas retas
    ay: float
    bx: float          # centro da peça na inclinada
    by: float
    nota: float        # IoU dos contornos (1 = encaixe perfeito)

    def ponto(self, x: float, y: float) -> Tuple[float, float]:
        t = np.radians(self.angulo)
        c, s = np.cos(t), np.sin(t)
        dx, dy = x - self.ax, y - self.ay
        return (self.bx + self.escala * (c * dx - s * dy), self.by + self.escala * (s * dx + c * dy))

    def para_dict(self) -> dict:
        return {k: float(getattr(self, k)) for k in ("angulo", "escala", "ax", "ay", "bx", "by", "nota")}


def _mascara_peca(im: Image.Image, lado: int) -> Tuple[np.ndarray, float]:
    k = lado / float(max(im.size))
    p = im.convert("RGBA").resize((max(1, round(im.size[0] * k)), max(1, round(im.size[1] * k))), Image.BILINEAR)
    a = np.asarray(p.getchannel("A")) > 128
    if a.all():  # sem transparência: separa do fundo claro pela cor do canto
        rgb = np.asarray(p.convert("RGB")).astype(np.int16)
        a = np.abs(rgb - rgb[2, 2]).sum(2) > 30
    return a, k


def registrar_inclinada(costas: Image.Image, incl: Image.Image) -> RegistroInclinado:
    """Busca o giro/escala que melhor encaixa o contorno das costas retas no da foto inclinada."""
    lado = 360
    A, ka = _mascara_peca(costas, lado)
    B, kb = _mascara_peca(incl, lado)
    ya, xa = np.nonzero(A)
    yb, xb = np.nonzero(B)
    ac = (xa.mean(), ya.mean())
    bc = (xb.mean(), yb.mean())
    s0 = np.sqrt(B.sum() / max(A.sum(), 1))
    imA = Image.fromarray((A * 255).astype(np.uint8))
    Hb, Wb = B.shape

    def iou(ang, esc, dx=0.0, dy=0.0):
        t = np.radians(ang)
        c, s = np.cos(t), np.sin(t)
        # inversa: ponto da inclinada -> ponto das costas
        m = [c / esc, s / esc, 0.0, -s / esc, c / esc, 0.0]
        cx, cy = bc[0] + dx, bc[1] + dy
        m[2] = ac[0] - (m[0] * cx + m[1] * cy)
        m[5] = ac[1] - (m[3] * cx + m[4] * cy)
        R = np.asarray(imA.transform((Wb, Hb), Image.AFFINE, m, Image.BILINEAR)) > 128
        return (R & B).sum() / max((R | B).sum(), 1)

    melhor = max(((iou(a, s0 * f), a, s0 * f) for a in range(-60, 61, 3) for f in (0.94, 1.0, 1.06)))
    _, ang, esc = melhor
    dx = dy = 0.0
    for passo_a, passo_s, passo_d in ((1.0, 0.015, 2.0), (0.4, 0.006, 1.0), (0.15, 0.002, 0.5)):
        melhorou = True
        while melhorou:
            melhorou = False
            base = iou(ang, esc, dx, dy)
            for da, ds, ddx, ddy in ((passo_a, 0, 0, 0), (-passo_a, 0, 0, 0), (0, passo_s, 0, 0), (0, -passo_s, 0, 0),
                                     (0, 0, passo_d, 0), (0, 0, -passo_d, 0), (0, 0, 0, passo_d), (0, 0, 0, -passo_d)):
                v = iou(ang + da, esc * (1 + ds), dx + ddx, dy + ddy)
                if v > base + 1e-5:
                    ang, esc, dx, dy, base, melhorou = ang + da, esc * (1 + ds), dx + ddx, dy + ddy, v, True
    nota = iou(ang, esc, dx, dy)
    # volta para pixels dos arquivos originais
    return RegistroInclinado(ang, esc * ka / kb, ac[0] / ka, ac[1] / ka, (bc[0] + dx) / kb, (bc[1] + dy) / kb, nota)


def registro_inclinada_em_cache(costas: Path, incl: Path, cache_json: Path,
                                manual: Optional[dict] = None) -> RegistroInclinado:
    if manual:
        return RegistroInclinado(**{k: float(manual[k]) for k in ("angulo", "escala", "ax", "ay", "bx", "by")}, nota=1.0)
    chave = f"incl|{costas.name}|{incl.name}|{_impressao(costas)}|{_impressao(incl)}"
    dados = {}
    if cache_json.exists():
        try:
            dados = json.loads(cache_json.read_text(encoding="utf-8"))
        except Exception:
            dados = {}
    if chave in dados:
        return RegistroInclinado(**dados[chave])
    reg = registrar_inclinada(carregar_imagem(costas), carregar_imagem(incl))
    dados[chave] = reg.para_dict()
    try:
        cache_json.parent.mkdir(parents=True, exist_ok=True)
        cache_json.write_text(json.dumps(dados, indent=1), encoding="utf-8")
    except OSError:
        pass
    return reg
