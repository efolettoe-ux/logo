"""Amostra do motor v3: leva a estampa do mockup liso aprovado (saida/) para as fotos do modelo.

Uso: python3 amostra_v3.py PRODUTO foto1,foto2,...   (ex.: CAPRESE branca-costas-close)
Os caminhos de trabalho (/tmp/claude-0/...) são os desta sessão; a saída vai para SAIDA_V3.
"""
import sys,json,os,csv
sys.path.insert(0,'/home/user/logo/automacao-estampas')
import numpy as np, cv2
from PIL import Image
from scipy import ndimage
from motor_v3 import achar_pontos, levar_camada, levar_camada_corpo, levar_camada_corpo_v2, compor, proporcao_axila, Pontos
from modelos import mascara_tecido_suave, mascara_pele, preparar_modelo, recolorir_camiseta
from imagem import carregar_estampa, Torso
R='/tmp/claude-0/pallacio-work/full/'; UP='/tmp/claude-0/-home-user-logo/2cf89407-8e22-55ba-910c-d0e8feb0d3ba/scratchpad/upload/'
OUT=os.environ.get('SAIDA_V3','/tmp/claude-0/amostra_v3')  # caminho separado: não sobrescreve nada; os.makedirs(OUT,exist_ok=True)
T=json.load(open('/home/user/logo/automacao-estampas/dados/torsos_modelos.json')); TOP=json.load(open('/tmp/claude-0/topos.json'))
CM=json.load(open('/tmp/claude-0/cores_mockup.json'))
mapa=list(csv.DictReader(open(R+'mapa.csv')))
COR={'preta':'Preta','branca':'Branca','off-white':'Off White','azul-marinho':'Azul Marinho'}
COD={'azul-marinho':'AZ','branca':'BR','off-white':'OW','preta':'PT'}
PONTOS_MANUAIS=json.load(open('/tmp/claude-0/v3/pontos_manuais.json')) if os.path.exists('/tmp/claude-0/v3/pontos_manuais.json') else {}
prod=sys.argv[1]; fotos=sys.argv[2].split(',')
_pm={}
def pontos_mockup(lado):
    if lado not in _pm:
        im=Image.open(f'/tmp/claude-0/cores5/mk5/branca-{lado}.png')
        m=(np.asarray(im)[...,3]>128).astype(np.uint8); _pm[lado]=(achar_pontos(m,gola_x=im.width/2),im.size)
    return _pm[lado]
def caixa_plana(prod,c,lado):
    """Caixa da estampa no mockup liso, tirada do mockup liso final aprovado (saida/)."""
    n={'costas':'01-costas','frente':'02-frente'}[lado]
    f=np.asarray(Image.open(f'{R}saida/{prod}/PALL-{prod}-{COD[c]}_{n}.png').convert('RGBA')).astype(int)
    b=np.asarray(Image.open(f'{R}mockups/{c}-{lado}.png').convert('RGBA').resize((f.shape[1],f.shape[0]))).astype(int)
    d=ndimage.binary_opening(np.abs(f[...,:3]-b[...,:3]).sum(-1)>40,iterations=2)
    ys,xs=np.nonzero(d); return xs.min(),ys.min(),xs.max()+1,ys.max()+1
for n in fotos:
    c=n.rsplit('-',2)[0]; lado='costas' if '-costas-' in n else 'frente'
    row=[r for r in mapa if r['NOME']==prod and r['cor']==COR[c] and r['lado']==lado][0]
    a=row['arquivo_estampa']; p=R+a if os.path.exists(R+a) else UP+a
    art=carregar_estampa(p)[0]
    pm,(MW,MH)=pontos_mockup(lado)
    x0,y0,x1,y1=caixa_plana(prod,c,lado)
    # camada no espaço do mockup liso
    camada=np.zeros((MH,MW,4),np.float32)
    aw=x1-x0; ah=round(aw*art.size[1]/art.size[0])
    a_=np.asarray(art.convert('RGBa').resize((aw,ah),Image.LANCZOS)).astype(np.float32)/255
    camada[y0:y0+ah,x0:x1]=a_[:max(0,min(ah,MH-y0))]
    rgb=np.where(camada[...,3:4]>1e-4,camada[...,:3]/np.maximum(camada[...,3:4],1e-4),0); camada[...,:3]=rgb
    # foto
    im=Image.open(f'/tmp/claude-0/mm/{n}.png').convert('RGBA'); W,H=im.size
    camisa=mascara_tecido_suave(im,TOP[n],T[n]['base'])
    pf=achar_pontos((camisa>0.5).astype(np.uint8), gola_x=T[n]['gola_x'], r_axila=proporcao_axila(pm))
    if n in PONTOS_MANUAIS: pf.p.update({k:tuple(v) for k,v in PONTOS_MANUAIS[n].items()})
    xs=[v[0] for v in pf.p.values()]; ys=[v[1] for v in pf.p.values()]
    cf=(max(0,int(min(xs))-60),max(0,int(min(ys))-60),min(W,int(max(xs))+60),min(H,int(max(ys))+60))
    lay=levar_camada_corpo_v2(camada,pm,pf,(W,H),cf,ancora_m=((x0+x1)/2,y0))
    # foto com a cor do mockup (mesma correção já aprovada)
    tor=Torso(T[n]['x0'],T[n]['x1'],TOP[n],T[n]['base'],TOP[n]+300,W,H)
    mk=preparar_modelo(f'/tmp/claude-0/mm/{n}.png',torso_manual=tor)
    recolorir_camiseta(mk,tuple(CM[c]),camisa)
    foto=mk.rgb.astype(np.float32)/255
    pele=ndimage.binary_dilation(mascara_pele(mk.rgb),iterations=2).astype(np.float32)
    pele=cv2.GaussianBlur(pele,(0,0),1.0)
    res=compor(foto,mk.alpha,camisa,pele,lay,tuple(np.array(CM[c])/255.0))
    outim=Image.fromarray(np.clip(res*255+0.5,0,255).astype(np.uint8),'RGB').convert('RGBA'); outim.putalpha(Image.fromarray(mk.alpha))
    outim.save(f'{OUT}/{prod}-{n}.png')
    print('ok',n,flush=True)
