"""Copia a estampa de um mockup liso oficial: separa a tinta da camiseta lisa (mesmo template do motor).
Não redesenha nada: alfa e cor saem da diferença pixel a pixel entre o mockup e a camiseta lisa.
Uso: python3 extrair_arte_mockup.py MOCKUP.png BASE_LISA.png SAIDA.png"""
import sys, json
import numpy as np, cv2
from PIL import Image
from scipy import ndimage

def extrair(mockup, base):
    I = np.asarray(Image.open(mockup).convert('RGBA')).astype(np.float32)
    B = np.asarray(Image.open(base).convert('RGBA')).astype(np.float32)
    d = np.abs(I[..., :3] - B[..., :3]).max(-1)
    tinta = ndimage.binary_opening(d > 18, iterations=1)
    tinta = ndimage.binary_dilation(tinta, iterations=2) & (d > 4)
    ys, xs = np.nonzero(tinta)
    x0, y0, x1, y1 = xs.min() - 2, ys.min() - 2, xs.max() + 3, ys.max() + 3
    I, B, d, tinta = I[y0:y1, x0:x1], B[y0:y1, x0:x1], d[y0:y1, x0:x1], tinta[y0:y1, x0:x1]
    # contraste "cheio" da tinta perto de cada pixel (máximo local): borda antisserrilhada vira alfa parcial
    cheio = cv2.dilate(d, np.ones((5, 5), np.uint8))
    a = np.clip((d - 4) / np.maximum(cheio - 4, 1), 0, 1) * tinta
    cor = (I[..., :3] - (1 - a[..., None]) * B[..., :3]) / np.maximum(a[..., None], 1e-3)
    cor = np.clip(np.where(a[..., None] > 0.02, cor, I[..., :3]), 0, 255)
    out = np.dstack([cor, a * 255]).round().astype(np.uint8)
    return Image.fromarray(out, 'RGBA'), (int(x0), int(y0))

if __name__ == '__main__':
    im, pos = extrair(sys.argv[1], sys.argv[2])
    im.save(sys.argv[3])
    json.dump(dict(origem=sys.argv[1], posicao_no_mockup=pos, tamanho=im.size), open(sys.argv[3][:-4] + '.json', 'w'))
    print(sys.argv[3], im.size, pos)
