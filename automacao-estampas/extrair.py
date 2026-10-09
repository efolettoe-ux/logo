"""Extrai a estampa das fotos atuais da loja quando não existe o arquivo da arte.

Para cada linha do mapa.csv sem arte (e com estampa na foto da loja da mesma cor e lado), recorta a
estampa da foto, separa a tinta do tecido ("color to alpha" contra a cor medida do tecido), amplia
com cuidado e salva um PNG transparente em estampas_da_loja/. A linha do mapa passa a apontar para
esse PNG (origem=manual, para não ser sobrescrita pelo casar).

A qualidade é limitada pela foto da loja (a estampa ocupa ~300-400 px nela). Para o produto final,
o ideal continua sendo o arquivo original da arte.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageFilter

from imagem import carregar_imagem

PASTA = "estampas_da_loja"


def separar_tinta(rgb: np.ndarray, tecido: Tuple[int, int, int], ruido: float = 0.10) -> np.ndarray:
    """RGB (HxWx3, 0-255) sobre um tecido liso -> RGBA (0-255) só com a tinta.

    Para cada pixel, a menor opacidade que explica a cor como tinta sobre o tecido (o "color to alpha"
    dos editores). Diferenças pequenas (sombra/dobra do tecido) viram transparência.
    """
    c = rgb.astype(np.float32) / 255.0
    b = np.array(tecido, np.float32) / 255.0
    acima = np.where(c > b, (c - b) / np.maximum(1.0 - b, 1e-3), 0.0)
    abaixo = np.where(c < b, (b - c) / np.maximum(b, 1e-3), 0.0)
    a = np.clip(np.max(np.maximum(acima, abaixo), axis=-1), 0.0, 1.0)
    # sombras e textura do tecido ficam abaixo de "ruido": some; acima disso, rampa suave até opaco
    a2 = np.clip((a - ruido) / max(1e-3, 1.0 - ruido), 0.0, 1.0)
    a2 = np.clip(a2 * 1.25, 0.0, 1.0)  # tinta sólida volta a ser 100% opaca
    with np.errstate(divide="ignore", invalid="ignore"):
        cor = b + (c - b) / np.maximum(a, 1e-3)[..., None]
    cor = np.clip(np.nan_to_num(cor), 0.0, 1.0)
    out = np.dstack([cor * 255.0, a2 * 255.0])
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def ampliar(rgba: Image.Image, fator: float) -> Image.Image:
    """Amplia com LANCZOS em alfa pré-multiplicado e devolve um pouco de nitidez às bordas."""
    w, h = rgba.size
    g = rgba.convert("RGBa").resize((max(1, round(w * fator)), max(1, round(h * fator))), Image.LANCZOS)
    g = g.convert("RGBA")
    rgb = g.convert("RGB").filter(ImageFilter.UnsharpMask(radius=1.6, percent=70, threshold=2))
    a = g.getchannel("A").filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=2))
    out = rgb.convert("RGBA")
    out.putalpha(a)
    return out


def recortar_da_foto(foto: str, bbox: Tuple[float, float, float, float], tecido: Tuple[int, int, int],
                     fator: float = 3.0, margem: int = 6) -> Image.Image:
    im = carregar_imagem(foto).convert("RGB")
    x0, y0, x1, y1 = bbox
    W, H = im.size
    caixa = (max(0, int(x0) - margem), max(0, int(y0) - margem), min(W, int(x1) + margem), min(H, int(y1) + margem))
    arr = np.asarray(im.crop(caixa))
    # cor do tecido medida na própria borda do recorte (a luz muda de foto para foto) e limiar de
    # ruído pela variação do tecido nessa borda: sombra e trama não viram "tinta" semitransparente
    borda = np.concatenate([arr[:3].reshape(-1, 3), arr[-3:].reshape(-1, 3), arr[:, :3].reshape(-1, 3),
                            arr[:, -3:].reshape(-1, 3)])
    tecido = tuple(int(v) for v in np.median(borda, axis=0))
    a_borda = separar_tinta(borda[None], tecido, ruido=0.0)[0, :, 3] / 255.0
    ruido = float(min(0.35, np.percentile(a_borda, 99) + 0.04))
    rgba = Image.fromarray(separar_tinta(arr, tecido, ruido), "RGBA")
    bb = rgba.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox()
    if bb:
        rgba = rgba.crop(bb)
    return ampliar(rgba, fator)


def extrair(raiz: Path, produtos: Optional[List[str]] = None, fator: float = 3.0,
            incluir_revisar: bool = False) -> Dict[str, int]:
    """Preenche as linhas sem arte do mapa.csv com estampas tiradas das fotos da loja."""
    analise = list(csv.DictReader(open(raiz / "analise.csv", encoding="utf-8")))
    caminho_mapa = raiz / "mapa.csv"
    with open(caminho_mapa, encoding="utf-8", newline="") as f:
        leitor = csv.DictReader(f)
        campos = leitor.fieldnames
        mapa = list(leitor)
    fotos = {}
    for a in analise:
        if a.get("tem_estampa") == "sim" and a.get("bbox_x0"):
            fotos.setdefault((a["handle"], a["cor"], a["lado"]), a)
    alvo = {p.upper() for p in produtos} if produtos else None
    cont = {"extraidas": 0, "sem_foto": 0}
    (raiz / PASTA).mkdir(exist_ok=True)
    for linha in mapa:
        if alvo and linha["NOME"].upper() not in alvo:
            continue
        sem_arte = not linha["arquivo_estampa"].strip()
        revisar = incluir_revisar and linha.get("revisar", "").strip().lower() == "sim"
        if not (sem_arte or revisar) or linha["arquivo_estampa"].strip().upper() == "LISO":
            continue
        a = fotos.get((linha["handle"], linha["cor"], linha["lado"]))
        if a is None:
            cont["sem_foto"] += 1
            continue
        tecido = tuple(int(v) for v in a["rgb_tecido"].split(","))
        bbox = tuple(float(a[k]) for k in ("bbox_x0", "bbox_y0", "bbox_x1", "bbox_y1"))
        art = recortar_da_foto(a["arquivo"], bbox, tecido, fator)
        nome = f"{linha['NOME']}_{linha['lado']}_{linha['cor'].replace(' ', '-')}.png"
        art.save(raiz / PASTA / nome)
        linha["arquivo_estampa"] = f"{PASTA}/{nome}"
        linha["origem"] = "manual"
        linha["revisar"] = "nao"
        linha["observacao"] = "estampa extraída da foto atual da loja (qualidade limitada pela foto)"
        for k, chave in (("largura_rel", "largura_rel"), ("topo_rel", "topo_rel"), ("centro_x_rel", "centro_x_rel")):
            if not linha.get(k) and a.get(chave):
                linha[k] = a[chave]
        cont["extraidas"] += 1
    with open(caminho_mapa, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(mapa)
    return cont
