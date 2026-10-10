"""Roda o motor v3.2 (aprovado na CAPRESE) em todas as estampas do mapa.csv e salva com o nome final.

Uso:
    python3 rodar_catalogo_modelos.py SAIDA [PRODUTO1,PRODUTO2,...]

- Precisa de dados/calibracao_caprese.json (já vem pronto; refaz com a CAPRESE se mudar algo).
- Cada produto roda em processo próprio (amostra_v31.py, INTEGRA=1 = v3.2) numa pasta temporária;
  depois as fotos são renomeadas para PALL-{PRODUTO}-{COR}_{04..07}-modelo-....png numa pasta ÚNICA.
- Só as 4 cores com foto de modelo (Azul Marinho, Branca, Off White, Preta). Bicolores não têm modelo.
- Produto com foto não gerada (pontos inválidos) ou com pixel alterado fora da tinta vai para o relatório.
"""
import csv, json, os, shutil, subprocess, sys

AQUI = os.path.dirname(os.path.abspath(__file__))
R = os.environ.get('PALLACIO_DIR', '/tmp/claude-0/pallacio-work/full/').rstrip('/') + '/'
CORES = {'Azul Marinho': ('azul-marinho', 'AZ'), 'Branca': ('branca', 'BR'),
         'Off White': ('off-white', 'OW'), 'Preta': ('preta', 'PT')}
NUM = {'costas-close': '04-modelo-costas-close', 'frente-close': '05-modelo-frente-close',
       'costas-corpo': '06-modelo-costas-corpo', 'frente-corpo': '07-modelo-frente-corpo'}

saida = sys.argv[1]
os.makedirs(saida, exist_ok=True)
mapa = list(csv.DictReader(open(R + 'mapa.csv')))
produtos = sorted(set(r['NOME'] for r in mapa))
if len(sys.argv) > 2:
    produtos = [p for p in produtos if p in sys.argv[2].split(',')]

relatorio = {}
for prod in produtos:
    cores = sorted(set(r['cor'] for r in mapa if r['NOME'] == prod and r['cor'] in CORES))
    if not cores:
        continue
    fotos = [f'{CORES[c][0]}-{v}' for c in cores for v in NUM]
    tmp = os.path.join(saida, '_tmp_' + prod)
    os.makedirs(tmp, exist_ok=True)
    env = dict(os.environ, SAIDA_V31=tmp, INTEGRA='1')
    env.pop('ACABAMENTO', None)                        # v3.2 aprovada: sem o granulado da v3.3
    r = subprocess.run([sys.executable, os.path.join(AQUI, 'amostra_v31.py'), prod, ','.join(fotos)],
                       env=env, capture_output=True, text=True)
    reg_arq = os.path.join(tmp, f'registro_{prod}.json')
    reg = json.load(open(reg_arq)) if os.path.exists(reg_arq) else {}
    problemas = []
    if r.returncode != 0:
        problemas.append('erro: ' + r.stderr[-800:])
    for c in cores:
        cn, cod = CORES[c]
        for v, nn in NUM.items():
            n = f'{cn}-{v}'
            info = reg.get(n)
            if not info or not info.get('gerada'):
                problemas.append(f'{n}: não gerada {info.get("problemas") if info else ""}')
                continue
            if info.get('pixels_alterados_fora_da_tinta', 0) != 0:
                problemas.append(f'{n}: {info["pixels_alterados_fora_da_tinta"]} pixels alterados fora da tinta')
                continue
            shutil.move(os.path.join(tmp, f'{prod}-{n}.png'), os.path.join(saida, f'PALL-{prod}-{cod}_{nn}.png'))
    relatorio[prod] = dict(ok=not problemas, problemas=problemas, registro=reg)
    shutil.rmtree(tmp, ignore_errors=True)
    print(prod, 'OK' if not problemas else problemas, flush=True)
    json.dump(relatorio, open(os.path.join(saida, '_relatorio_modelos.json'), 'w'), indent=1, ensure_ascii=False)
