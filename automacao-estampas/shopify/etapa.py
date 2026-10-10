"""Auxiliar do lote Shopify.
  etapa.py galeria SPEC.json   -> define cor principal, monta galeria (montar_galeria), imprime variáveis do productUpdate
  etapa.py variantes SPEC.json NOVAS.txt -> NOVAS.txt: linhas "mediaId nomeArquivo"; imprime variáveis do productVariantsBulkUpdate
  etapa.py remover SPEC.json   -> variáveis do fileUpdate (tira as antigas do produto, mantém em Arquivos)
SPEC: {handle, pid, featured, cores:[..ordem do seletor..], variantes:{cor:[ids]}, midia_por_cor:{cor:id}, antigas:[ids], featured_url}"""
import json, sys, os, re, subprocess, io
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from montar_galeria import montar, cod_cor
D = os.path.dirname(os.path.abspath(__file__))

def cor_pela_imagem(url):
    import numpy as np
    from PIL import Image
    b = subprocess.run(['curl', '-sL', '-m', '30', url], capture_output=True).stdout
    im = Image.open(io.BytesIO(b)).convert('RGB'); w, h = im.size
    a = np.asarray(im.crop((int(w*.3), int(h*.6), int(w*.7), int(h*.8)))).reshape(-1, 3).astype(float)
    m = np.median(a, 0)
    ref = {'Branca': (244, 244, 244), 'Off White': (241, 234, 221), 'Preta': (15, 15, 16), 'Azul Marinho': (22, 34, 60)}
    return min(ref, key=lambda k: sum((m - np.array(ref[k]))**2)), m.round().tolist()

def principal(s):
    for cor, mid in s.get('midia_por_cor', {}).items():
        if mid and mid.split('/')[-1] == s['featured'].split('/')[-1]:
            return cor, 'imagem principal = imagem das variantes desta cor'
    m = re.search(r'-(AZ|BR|OW|PT|BR-AZL|BR-AZC|BR-AZE|BR-PT|PT-VM)_0', s.get('featured_url', ''))
    if m:
        for c in s['cores']:
            if cod_cor(c) == m.group(1): return c, 'código de cor no nome da imagem principal'
    c, med = cor_pela_imagem(s['featured_url'])
    for x in s['cores']:
        if x.lower() == c.lower(): return x, f'cor analisada na imagem principal {med}'
    return s['cores'][0], 'sem identificação: primeira cor do seletor'

if __name__ == '__main__' and sys.argv[1] in ('galeria', 'variantes', 'remover'):
    acao, spec = sys.argv[1], json.load(open(sys.argv[2]))
    if acao == 'galeria':
        cor, motivo = principal(spec)
        g = montar(spec['handle'], spec['cores'], cor)
        g.update(cor_principal=cor, motivo=motivo)
        json.dump(g, open(f"{D}/manifestos/{spec['handle']}_galeria.json", 'w'), ensure_ascii=False, indent=1)
        json.dump(spec, open(f"{D}/manifestos/{spec['handle']}_antes.json", 'w'), ensure_ascii=False, indent=1)
        print('PRINCIPAL', cor, '|', motivo, '| ordem', g.get('ordem_cores'), '| itens', len(g.get('itens', [])),
              '| faltando', g.get('faltando'), g.get('sem_url'), '| completo', g.get('completo'), '| pendente_manual', g.get('pendente_manual'))
        if g.get('completo'):
            print(json.dumps({'id': spec['pid'], 'media': [{'originalSource': i['url'], 'mediaContentType': 'IMAGE', 'alt': ''} for i in g['itens']]}))
    elif acao == 'variantes':
        g = json.load(open(f"{D}/manifestos/{spec['handle']}_galeria.json"))
        novas = dict(l.split()[::-1] for l in open(sys.argv[3]) if l.strip())   # nome -> id
        def id_de(nome):
            base = nome[:-4]
            for k, v in novas.items():
                if k == nome or re.fullmatch(re.escape(base) + r'(_[0-9a-f-]{36})?\.png', k): return v
        v = []
        for cor, ids in spec['variantes'].items():
            um = [i['nome'] for i in g['itens'] if i['cor'] == cor and i['nn'] == '01'][0]
            mid = id_de(um); assert mid, um
            v += [{'id': f'gid://shopify/ProductVariant/{x}', 'mediaId': f'gid://shopify/MediaImage/{mid}'} for x in ids]
        faltam = [i['nome'] for i in g['itens'] if not id_de(i['nome'])]
        print('FALTAM_NOVAS', faltam)
        print(json.dumps({'pid': spec['pid'], 'v': v}))
    elif acao == 'remover':
        print(json.dumps({'files': [{'id': f'gid://shopify/MediaImage/{x}', 'referencesToRemove': [spec['pid']]} for x in spec['antigas']]}))

def variantes_por_ids(spec, mapa_ids):
    v = []
    for cor, ids in spec['variantes'].items():
        v += [{'id': f'gid://shopify/ProductVariant/{x}', 'mediaId': f'gid://shopify/MediaImage/{mapa_ids[cor]}'} for x in ids]
    return {'pid': spec['pid'], 'v': v}

if __name__ == '__main__' and sys.argv[1] == 'var':
    spec = json.load(open(sys.argv[2])); m = dict(a.split('=') for a in sys.argv[3:])
    assert set(m) == set(spec['variantes']), (set(m), set(spec['variantes']))
    print(json.dumps(variantes_por_ids(spec, m)))

if __name__ == '__main__' and sys.argv[1] == 'csv':
    # etapa.py csv HANDLE removidas status obs
    g = json.load(open(f"{D}/manifestos/{sys.argv[2]}_galeria.json")); s = json.load(open(f"{D}/manifestos/{sys.argv[2]}_antes.json"))
    nd = sum(1 for i in g['itens'] if i['origem'] == 'drive'); nm = sum(1 for i in g['itens'] if i['origem'] == 'modelo')
    import csv as _c
    with open(f'{D}/conferencia.csv', 'a', newline='') as f:
        _c.writer(f).writerow([g['produto'], s['pid'], g['cor_principal'], g['ordem_cores'][0], nd, nm, nd + nm, sys.argv[3], sys.argv[4], ' '.join(sys.argv[5:]) or g['motivo']])
    print('ok', g['produto'])

if __name__ == '__main__' and sys.argv[1] == 'mk':
    # etapa.py mk handle pid featured featured_url "Cor1|Cor2" primeira_var ultima_var "Cor=mid,Cor=mid" "ant1,ant2" [tamanhos=6]
    _, _, h, pid, fe, fu, cores, v0, v1, mpc, ant = sys.argv[:11]
    nt = int(sys.argv[11]) if len(sys.argv) > 11 else 6
    cores = cores.split('|'); n = len(cores) * nt; v0, v1 = int(v0), int(v1)
    assert v1 == v0 + (n - 1) * 32768, f'IDs de variantes não sequenciais: {v0}..{v1} para {n}'
    ids = [str(v0 + i * 32768) for i in range(n)]
    spec = dict(handle=h, pid=f'gid://shopify/Product/{pid}', featured=fe, featured_url=fu, cores=cores,
                variantes={c: ids[i*nt:(i+1)*nt] for i, c in enumerate(cores)},
                midia_por_cor=dict(x.split('=') for x in mpc.split(',')), antigas=ant.split(','))
    json.dump(spec, open('/tmp/claude-0/spec.json', 'w'), ensure_ascii=False)
    print('spec ok', h, len(ids), 'variantes')

if __name__ == '__main__' and sys.argv[1] == 'var2':
    # etapa.py var2 SPEC primeiro_id_novo  (IDs das mídias novas são sequenciais de 32768 na ordem enviada)
    spec = json.load(open(sys.argv[2])); g = json.load(open(f"{D}/manifestos/{spec['handle']}_galeria.json"))
    p0 = int(sys.argv[3]); m = {}
    for k, i in enumerate(g['itens']):
        if i['nn'] == '01': m[i['cor']] = str(p0 + k * 32768)
    print('01:', m, file=sys.stderr)
    print(json.dumps(variantes_por_ids(spec, m)))

if __name__ == '__main__' and sys.argv[1] == 'mk2':
    # etapa.py mk2 handle pid featured featured_url "Cor=primeiro_var_id|..." "Cor=mid,..." "ant1,ant2" [tamanhos=6]
    _, _, h, pid, fe, fu, cv, mpc, ant = sys.argv[:9]
    nt = int(sys.argv[9]) if len(sys.argv) > 9 else 6
    pares = [x.split('=') for x in cv.split('|')]
    spec = dict(handle=h, pid=f'gid://shopify/Product/{pid}', featured=fe, featured_url=fu, cores=[c for c, _ in pares],
                variantes={c: [str(int(v) + i * 32768) for i in range(nt)] for c, v in pares},
                midia_por_cor=dict(x.split('=') for x in mpc.split(',')), antigas=ant.split(','))
    json.dump(spec, open('/tmp/claude-0/spec.json', 'w'), ensure_ascii=False)
    print('spec ok', h, {c: (v[0], v[-1]) for c, v in spec['variantes'].items()})
