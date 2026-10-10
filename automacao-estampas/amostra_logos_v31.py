"""Teste v3.1 das logos pequenas da frente: PNG oficial (recorte fiel), uma única transformação
(giro + escala + perspectiva), antisserrilhado de alta qualidade, luz suave. Saída em caminho separado."""
import sys,json,os,csv
sys.path.insert(0,'/home/user/logo/automacao-estampas')
import numpy as np, cv2
from PIL import Image
from scipy import ndimage
from motor_v3 import achar_pontos, proporcao_axila, carregar_arte_fiel, afim_logo, render_afim, compor_logo
from modelos import mascara_tecido_suave, mascara_pele, preparar_modelo, recolorir_camiseta
from imagem import Torso
R='/tmp/claude-0/pallacio-work/full/'; UP='/tmp/claude-0/-home-user-logo/2cf89407-8e22-55ba-910c-d0e8feb0d3ba/scratchpad/upload/'
OUT='/tmp/claude-0/amostra_v31'; os.makedirs(OUT,exist_ok=True)
T=json.load(open('/home/user/logo/automacao-estampas/dados/torsos_modelos.json')); TOP=json.load(open('/tmp/claude-0/topos.json'))
CM=json.load(open('/tmp/claude-0/cores_mockup.json')); mapa=list(csv.DictReader(open(R+'mapa.csv')))
COR={'preta':'Preta','branca':'Branca','off-white':'Off White','azul-marinho':'Azul Marinho'}; COD={'azul-marinho':'AZ','branca':'BR','off-white':'OW','preta':'PT'}
prod=sys.argv[1]; fotos=sys.argv[2].split(',')
im=Image.open('/tmp/claude-0/cores5/mk5/branca-frente.png'); pm=achar_pontos((np.asarray(im)[...,3]>128).astype(np.uint8),gola_x=im.width/2)
def faixa(perfil):
    c=np.cumsum(perfil,dtype=np.float64); t=c[-1]; return int(np.searchsorted(c,t*0.0015)),int(np.searchsorted(c,t*0.9985))
def caixa_plana(c):
    f=np.asarray(Image.open(f'{R}saida/{prod}/PALL-{prod}-{COD[c]}_02-frente.png').convert('RGBA')).astype(int)
    b=np.asarray(Image.open(f'{R}mockups/{c}-frente.png').convert('RGBA')).astype(int)
    d=ndimage.binary_opening(np.abs(f[...,:3]-b[...,:3]).sum(-1)>40,iterations=2); ys,xs=np.nonzero(d); return xs.min(),ys.min(),xs.max()+1,ys.max()+1
log={}
for n in fotos:
    c=n.rsplit('-',2)[0]
    row=[r for r in mapa if r['NOME']==prod and r['cor']==COR[c] and r['lado']=='frente'][0]
    a=row['arquivo_estampa']; p=R+a if os.path.exists(R+a) else UP+a
    arte,(fx0,fy0,fx1,fy1),tem_alpha=carregar_arte_fiel(p)
    al=np.asarray(Image.open(p).convert('RGBA'))[...,3]>24
    ox0,ox1=faixa(al.sum(0)); oy0,oy1=faixa(al.sum(1))         # recorte antigo (o que o mockup liso usou)
    bx0,by0,bx1,by1=caixa_plana(c)
    s=(bx1-bx0)/(ox1-ox0+1)                                       # px do mockup por px do PNG oficial
    A=np.array([[s,0,bx0+(fx0-ox0)*s],[0,s,by0+(fy0-oy0)*s],[0,0,1]])   # arte -> mockup
    centro_m=tuple((A@np.array([arte.size[0]/2,arte.size[1]/2,1]))[:2])
    camisa=mascara_tecido_suave(Image.open(f'/tmp/claude-0/mm/{n}.png'),TOP[n],T[n]['base'])
    pf=achar_pontos((camisa>0.5).astype(np.uint8),gola_x=T[n]['gola_x'],r_axila=proporcao_axila(pm))
    M,info=afim_logo(pm,pf,centro_m)
    Maf=(np.vstack([M,[0,0,1]])@A)[:2]
    W,H=1344,2400
    lay=render_afim(arte,Maf,(W,H))
    tor=Torso(T[n]['x0'],T[n]['x1'],TOP[n],T[n]['base'],TOP[n]+300,W,H)
    mk=preparar_modelo(f'/tmp/claude-0/mm/{n}.png',torso_manual=tor); recolorir_camiseta(mk,tuple(CM[c]),camisa)
    pele=cv2.GaussianBlur(ndimage.binary_dilation(mascara_pele(mk.rgb),iterations=2).astype(np.float32),(0,0),1.0)
    res=compor_logo(mk.rgb,camisa,pele,lay,tuple(np.array(CM[c])/255.0))
    # verificação: fora da tinta, idêntico à base
    fora=lay[...,3]<=1e-4; difs=int((res[fora]!=mk.rgb[fora]).any(-1).sum())
    o=Image.fromarray(res,'RGB').convert('RGBA'); o.putalpha(Image.fromarray(mk.alpha)); o.save(f'{OUT}/{prod}-{n}.png')
    log[n]=dict(arquivo=a,png_oficial_com_transparencia=tem_alpha,tamanho_png=Image.open(p).size,recorte_fiel=[int(v) for v in (fx0,fy0,fx1,fy1)],
                escala_final=float(np.sqrt(abs(np.linalg.det(Maf[:,:2])))),giro_logo_graus=round(float(info['inclinacao_graus']),2),
                achatamento=round(float(info['sx']/info['sy']),3),pixels_alterados_fora_da_tinta=difs)
    print(n,log[n],flush=True)
json.dump(log,open(f'{OUT}/registro.json','w'),indent=1,ensure_ascii=False)
