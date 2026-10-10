"""Monta a galeria final de um produto da Shopify: mockups padrão 01-03 (Google Drive) + modelo 04-07 (projeto).
Uso: python3 montar_galeria.py HANDLE "Cor1|Cor2|..." "CorPrincipal"
Saída (stdout, JSON): ordem final [{nome, url, cor, nn}], faltando [...], completo (bool)."""
import csv, json, os, re, subprocess, sys
AQUI = os.path.dirname(os.path.abspath(__file__))
R = '/tmp/claude-0/pallacio-work/full/'
DRIVE = json.load(open(f'{AQUI}/mockups_drive_urls.json')) if os.path.exists(f'{AQUI}/mockups_drive_urls.json') else {}
ZIPLIST = f'{AQUI}/lista_zip_drive.txt'
COD = {'branca': 'BR', 'off white': 'OW', 'preta': 'PT', 'azul marinho': 'AZ', 'branca / azul': 'BR-AZL',
       'branca / azul claro': 'BR-AZC', 'branca / azul escuro': 'BR-AZE', 'branca / preta': 'BR-PT',
       'preta/vermelha': 'PT-VM', 'preta / vermelha': 'PT-VM'}
BR_MODELO = {'AZ': 'azul-marinho', 'BR': 'branca', 'OW': 'off-white', 'PT': 'preta'}
MODELO = {'04': 'modelo-costas-close', '05': 'modelo-frente-close', '06': 'modelo-costas-corpo', '07': 'modelo-frente-corpo'}
PENDENTES = set(json.load(open(f'{AQUI}/pendentes.json'))) if os.path.exists(f'{AQUI}/pendentes.json') else set()
SEM_MODELO = {'STUDIOS'}          # dono: STUDIOS não precisa de mockup com modelo

def cod_cor(nome):
    return COD.get(re.sub(r'\s+', ' ', nome.strip().lower()))

_arvores = {}
def arvore(br):
    if br not in _arvores:
        r = subprocess.run(['git', '-C', '/home/user/logo', 'ls-tree', '--name-only', f'origin/{br}'], capture_output=True, text=True)
        _arvores[br] = set(r.stdout.split())
    return _arvores[br]

def zip_nomes():
    return set(l.strip() for l in open(ZIPLIST))

def montar(handle, cores, principal):
    mapa = list(csv.DictReader(open(R + 'mapa.csv')))
    nomes = sorted(set(r['NOME'] for r in mapa if r['handle'] == handle))
    if len(nomes) != 1:
        return dict(erro=f'handle {handle} -> {nomes}')
    P = nomes[0]
    ordem = [principal] + [c for c in cores if c != principal]
    zn = zip_nomes(); itens, faltando = [], []
    for cor in ordem:
        c = cod_cor(cor)
        if not c:
            faltando.append(f'cor desconhecida: {cor}'); continue
        planos = sorted(n for n in zn if n.startswith(f'PALL-{P}-{c}_0') and n[len(f'PALL-{P}-{c}_'):][:2] in ('01', '02', '03'))
        nums = [n[len(f'PALL-{P}-{c}_'):][:2] for n in planos]
        esperado = ['01', '02'] if P in SEM_MODELO else ['01', '02', '03']
        for nn in esperado:
            if nn not in nums: faltando.append(f'PALL-{P}-{c}_{nn} (Drive)')
        for n in planos:
            itens.append(dict(nome=n, url=DRIVE.get(n), cor=cor, nn=n[len(f'PALL-{P}-{c}_'):][:2], origem='drive'))
        if c in BR_MODELO and P not in SEM_MODELO:
            for nn, d in MODELO.items():
                n = f'PALL-{P}-{c}_{nn}-{d}.png'
                br = 'modelos-v32-novas' if n in arvore('modelos-v32-novas') else f'modelos-v32-{BR_MODELO[c]}'
                if n in arvore(br):
                    itens.append(dict(nome=n, url=f'https://raw.githubusercontent.com/efolettoe-ux/logo/{br}/{n}', cor=cor, nn=nn, origem='modelo'))
                else:
                    faltando.append(f'{n} (modelo)')
    sem_url = [i['nome'] for i in itens if not i['url']]
    return dict(produto=P, handle=handle, ordem_cores=ordem, itens=itens, faltando=faltando, sem_url=sem_url,
                pendente_manual=P in PENDENTES, completo=not faltando and not sem_url and P not in PENDENTES)

if __name__ == '__main__':
    print(json.dumps(montar(sys.argv[1], sys.argv[2].split('|'), sys.argv[3]), ensure_ascii=False, indent=1))
