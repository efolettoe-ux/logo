"""Amostra v3.1 (fotos de modelo): uso python3 amostra_v31.py PRODUTO foto1,foto2,...

- arte: PNG oficial com recorte fiel (sem cortar traços), sem nenhuma alteração de pixels;
- costas: do PNG direto para a foto (elipse do tronco, escala única), altura = v2 aprovada;
- frente (logo pequena): uma transformação mínima (giro + escala + perspectiva), posição
  equilibrada no peito (mesma fração do tronco em todas as fotos) e altura da v2 aprovada;
- validação dos pontos do corpo antes de gerar (foto com ponto incoerente não é gerada);
- fora da tinta, os pixels ficam idênticos à foto base (conferido e registrado).
Saída em SAIDA_V31 (caminho separado; não sobrescreve nada).
"""
import sys, json, os, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, cv2
from PIL import Image
from scipy import ndimage
from motor_v3 import (achar_pontos, proporcao_axila, validar_pontos, carregar_arte_fiel, afim_logo, render_afim,
                      compor_logo, render_corpo, compor_v31, _x_de_f)
from modelos import mascara_tecido_suave, mascara_pele, preparar_modelo, recolorir_camiseta
from imagem import Torso

AQUI = os.path.dirname(os.path.abspath(__file__))
R = '/tmp/claude-0/pallacio-work/full/'
UP = '/tmp/claude-0/-home-user-logo/2cf89407-8e22-55ba-910c-d0e8feb0d3ba/scratchpad/upload/'
FOTOS_DIR = '/tmp/claude-0/mm/'
MOCKUPS = '/tmp/claude-0/cores5/mk5/'
OUT = os.environ.get('SAIDA_V31', '/tmp/claude-0/amostra_v31_completa')
os.makedirs(OUT, exist_ok=True)
T = json.load(open(f'{AQUI}/dados/torsos_modelos.json'))
TOP = json.load(open('/tmp/claude-0/topos.json'))
MAN = {k: v for k, v in json.load(open(f'{AQUI}/dados/pontos_manuais.json')).items() if not k.startswith('_')}
REF = json.load(open(f'{AQUI}/dados/referencia_v2_posicao.json'))
AJ = {k: v for k, v in json.load(open(f'{AQUI}/dados/ajustes_v31.json')).items() if not k.startswith('_')} \
    if os.path.exists(f'{AQUI}/dados/ajustes_v31.json') else {}
CM = json.load(open('/tmp/claude-0/cores_mockup.json'))
mapa = list(csv.DictReader(open(R + 'mapa.csv')))
COR = {'preta': 'Preta', 'branca': 'Branca', 'off-white': 'Off White', 'azul-marinho': 'Azul Marinho'}
COD = {'azul-marinho': 'AZ', 'branca': 'BR', 'off-white': 'OW', 'preta': 'PT'}
F_LOGO = 0.40      # centro da logo da frente: fração do meio tronco (média das frentes aprovadas)

_pm = {}
def pontos_mockup(lado):
    if lado not in _pm:
        im = Image.open(f'{MOCKUPS}branca-{lado}.png')
        _pm[lado] = achar_pontos((np.asarray(im)[..., 3] > 128).astype(np.uint8), gola_x=im.width / 2)
    return _pm[lado]

def faixa(perfil):
    c = np.cumsum(perfil, dtype=np.float64); t = c[-1]
    return int(np.searchsorted(c, t * 0.0015)), int(np.searchsorted(c, t * 0.9985))

def arte_e_posicao(prod, c, lado):
    """Arte fiel + transformação arte -> mockup liso. A caixa vem do mockup liso aprovado (saida/),
    que usou o recorte antigo: alinha pelo mesmo ponto para manter posição e escala aprovadas."""
    row = [r for r in mapa if r['NOME'] == prod and r['cor'] == COR[c] and r['lado'] == lado][0]
    a = row['arquivo_estampa']
    if a.strip().upper() == 'LISO':
        return None
    p = R + a if os.path.exists(R + a) else UP + a
    arte, (fx0, fy0, fx1, fy1), tem_alpha = carregar_arte_fiel(p)
    from imagem import carregar_estampa
    velha = carregar_estampa(p)[0]                     # só para saber onde o recorte antigo começava
    orig = np.asarray(Image.open(p).convert('RGBA'))[..., 3] > 24
    if tem_alpha:
        ox0, _ = faixa(orig.sum(0)); oy0, _ = faixa(orig.sum(1))
    else:
        ox0, oy0 = fx0, fy0
    n = {'costas': '01-costas', 'frente': '02-frente'}[lado]
    f = np.asarray(Image.open(f'{R}saida/{prod}/PALL-{prod}-{COD[c]}_{n}.png').convert('RGBA')).astype(int)
    b = np.asarray(Image.open(f'{R}mockups/{c}-{lado}.png').convert('RGBA')).astype(int)
    d = ndimage.binary_opening(np.abs(f[..., :3] - b[..., :3]).sum(-1) > 40, iterations=2)
    ys, xs = np.nonzero(d)
    bx0, by0, bx1 = xs.min(), ys.min(), xs.max() + 1
    s = (bx1 - bx0) / float(velha.size[0])
    A = np.array([[s, 0, bx0 + (fx0 - ox0) * s], [0, s, by0 + (fy0 - oy0) * s], [0, 0, 1]])
    return dict(arte=arte, A=A, arquivo=a, png_com_transparencia=tem_alpha, tamanho_png=Image.open(p).size,
                recorte_fiel=[int(fx0), int(fy0), int(fx1), int(fy1)])

INTEGRA = os.environ.get('INTEGRA') == '1'      # v3.2: tinta integrada à fotografia

def nitidez(img_u8, mascara):
    g = cv2.cvtColor(img_u8, cv2.COLOR_RGB2GRAY).astype(np.float32)
    e = np.abs(cv2.Laplacian(g, cv2.CV_32F))
    return float(np.percentile(e[mascara], 99.5)) if mascara.any() else 0.0

def params_integracao(n, alpha):
    """Branco/preto da cena e nitidez da câmera, medidos na própria foto do modelo."""
    orig = np.asarray(Image.open(f'{FOTOS_DIR}{n}.png').convert('RGB'))
    pessoa = alpha > 200
    lum = cv2.cvtColor(orig, cv2.COLOR_RGB2GRAY)
    lo, hi = np.percentile(lum[pessoa], [0.5, 99.5]) / 255.0
    from motor_v3 import srgb_lin
    return dict(branco=float(srgb_lin(np.float32(hi))), preto=float(srgb_lin(np.float32(lo))), dessat=0.05,
                nitidez_foto=nitidez(orig, pessoa & (np.arange(orig.shape[0])[:, None] > 0)))

DESFOQUE = {'costas': 0.55, 'frente': 0.35}   # suavidade de câmera (px); logo pequena protegida

def escolher_desfoque(compor, integra, tinta_de, lado):
    integra['desfoque'] = DESFOQUE[lado]
    return compor(integra), integra['desfoque']

registro = {}
prod = sys.argv[1]
for n in sys.argv[2].split(','):
    c = n.rsplit('-', 2)[0]; lado = 'costas' if '-costas-' in n else 'frente'
    pm = pontos_mockup(lado)
    im = Image.open(f'{FOTOS_DIR}{n}.png').convert('RGBA'); W, H = im.size
    camisa = mascara_tecido_suave(im, TOP[n], T[n]['base'])
    pf = achar_pontos((camisa > 0.5).astype(np.uint8), gola_x=T[n]['gola_x'], r_axila=proporcao_axila(pm))
    if n in MAN:
        pf.p.update({k: tuple(v) for k, v in MAN[n].items()})
    prob = validar_pontos(pf)
    if prob:
        registro[n] = dict(gerada=False, problemas=prob); print(n, 'NÃO GERADA:', prob); continue
    tor = Torso(T[n]['x0'], T[n]['x1'], TOP[n], T[n]['base'], TOP[n] + 300, W, H)
    mk = preparar_modelo(f'{FOTOS_DIR}{n}.png', torso_manual=tor)
    recolorir_camiseta(mk, tuple(CM[c]), camisa)
    base = mk.rgb.copy()
    pele = cv2.GaussianBlur(ndimage.binary_dilation(mascara_pele(mk.rgb), iterations=2).astype(np.float32), (0, 0), 1.0)
    info = arte_e_posicao(prod, c, lado)
    if info is None:
        res = base; detalhe = 'lisa'
    elif lado == 'frente':
        A = info['A']; arte = info['arte']
        centro_m = tuple((A @ np.array([arte.size[0] / 2, arte.size[1] / 2, 1]))[:2])
        M, geo = afim_logo(pm, pf, centro_m, f_centro=F_LOGO, y_centro_f=REF[n]['cy'],
                           giro_extra_graus=AJ.get(n, {}).get('giro_extra_graus', 0.0))
        Maf = (np.vstack([M, [0, 0, 1]]) @ A)[:2]
        lay = render_afim(arte, Maf, (W, H))
        if INTEGRA:
            integ = params_integracao(n, mk.alpha)
            res, sg = escolher_desfoque(lambda ig: compor_logo(base, camisa, pele, lay, tuple(np.array(CM[c]) / 255.0), integra=ig),
                                        integ, lambda: compor_logo.tinta, 'frente')
        else:
            res = compor_logo(base, camisa, pele, lay, tuple(np.array(CM[c]) / 255.0))
        detalhe = dict(tipo='logo pequena (transformação mínima)', giro_graus=round(float(geo['inclinacao_graus']), 2),
                       achatamento=round(float(geo['sx'] / geo['sy']), 3))
    else:
        A = info['A']; arte = info['arte']
        ancora_m = tuple((A @ np.array([arte.size[0] / 2, 0, 1]))[:2])      # topo-centro da arte
        xs = [v[0] for v in pf.p.values()]; ys = [v[1] for v in pf.p.values()]
        cf = (max(0, int(min(xs)) - 40), max(0, int(min(ys)) - 60), min(W, int(max(xs)) + 40), min(H, int(max(ys)) + 40))
        # posição e largura de referência = v2 aprovada (centro, topo e largura), foto por foto.
        # 1ª passada mede a largura que a geometria dá; 2ª corrige só a escala para igualar a v2.
        xr = (REF[n]['x0'] + REF[n]['x1']) / 2.0
        lay = render_corpo(arte, A, pm, pf, (W, H), cf, ancora_m, y_ancora_f=REF[n]['topo'], x_ancora_f=xr)
        xs_t = np.nonzero(lay[..., 3].max(0) > 0.5)[0]
        larg = float(xs_t.max() - xs_t.min()) if len(xs_t) else 1.0
        esc = (REF[n]['x1'] - REF[n]['x0']) / larg if larg > 1 else 1.0
        for _ in range(2):                                     # centro da tinta final = centro da v2
            lay = render_corpo(arte, A, pm, pf, (W, H), cf, ancora_m, y_ancora_f=REF[n]['topo'], x_ancora_f=xr, escala_mult=esc)
            xs_t = np.nonzero(lay[..., 3].max(0) > 0.5)[0]
            dx = (REF[n]['x0'] + REF[n]['x1']) / 2.0 - (xs_t.min() + xs_t.max()) / 2.0
            if abs(dx) < 2:
                break
            xr += dx
        if INTEGRA:
            integ = params_integracao(n, mk.alpha)
            res, sg = escolher_desfoque(lambda ig: compor_v31(base, camisa, pele, lay, tuple(np.array(CM[c]) / 255.0), integra=ig),
                                        integ, lambda: compor_v31.tinta, 'costas')
        else:
            res = compor_v31(base, camisa, pele, lay, tuple(np.array(CM[c]) / 255.0))
        detalhe = dict(tipo='estampa grande (elipse do tronco; centro, topo e largura = v2 aprovada)',
                       ajuste_escala=round(float(esc), 3))
    if info is None:
        tinta = np.zeros((H, W), bool)
    else:
        tinta = (compor_logo.tinta if lado == 'frente' else compor_v31.tinta)
    mudou_fora = int((np.any(res != base, axis=-1) & ~tinta).sum())   # tem que ser 0
    o = Image.fromarray(res, 'RGB').convert('RGBA'); o.putalpha(Image.fromarray(mk.alpha))
    o.save(f'{OUT}/{prod}-{n}.png')
    if INTEGRA and info is not None:
        detalhe = dict(detalhe, integracao={k: round(float(v), 4) for k, v in integ.items()})
    registro[n] = dict(gerada=True, arquivo_estampa=info['arquivo'] if info else 'LISO',
                       png_oficial_com_transparencia=info['png_com_transparencia'] if info else None,
                       tamanho_png=info['tamanho_png'] if info else None,
                       recorte_fiel=info['recorte_fiel'] if info else None,
                       pixels_alterados_fora_da_tinta=mudou_fora, detalhe=detalhe)
    print(n, registro[n], flush=True)
json.dump(registro, open(f'{OUT}/registro_{prod}.json', 'w'), indent=1, ensure_ascii=False)
