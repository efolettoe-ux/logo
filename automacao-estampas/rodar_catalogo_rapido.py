"""Catálogo de fotos de modelo (motor v3.2 aprovado), em paralelo e com cache.

Uso:
    python3 rodar_catalogo_rapido.py SAIDA [--produtos A,B] [--pular A,B] [--sem-frente-centralizada] [--workers N]

- Divide o trabalho em tarefas (produto, cor) = 4 fotos cada e roda N ao mesmo tempo (padrão: nº de núcleos),
  cada uma num processo com 1 thread (sem disputa de CPU).
- O preparo de cada foto do modelo fica em cache (CACHE_MODELOS) e é reaproveitado por todas as estampas.
- Salva PALL-{PRODUTO}-{COR}_{04..07}-modelo-....png numa pasta ÚNICA e _relatorio_modelos.json.
- Retoma de onde parou: tarefa com as 4 fotos já na saída é pulada.
- --sem-frente-centralizada: deixa de fora produto cuja estampa da frente é centralizada no peito
  (|centro_x_rel| < 0,1 no mapa.csv, ex.: AIRLINES).
"""
import argparse, csv, json, os, shutil, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed

AQUI = os.path.dirname(os.path.abspath(__file__))
R = os.environ.get('PALLACIO_DIR', '/tmp/claude-0/pallacio-work/full/').rstrip('/') + '/'
CORES = {'Azul Marinho': ('azul-marinho', 'AZ'), 'Branca': ('branca', 'BR'),
         'Off White': ('off-white', 'OW'), 'Preta': ('preta', 'PT')}
NUM = {'costas-close': '04-modelo-costas-close', 'frente-close': '05-modelo-frente-close',
       'costas-corpo': '06-modelo-costas-corpo', 'frente-corpo': '07-modelo-frente-corpo'}

ap = argparse.ArgumentParser()
ap.add_argument('saida')
ap.add_argument('--produtos', default='')
ap.add_argument('--pular', default='')
ap.add_argument('--sem-frente-centralizada', action='store_true')
ap.add_argument('--workers', type=int, default=os.cpu_count() or 4)
a = ap.parse_args()
os.makedirs(a.saida, exist_ok=True)

mapa = list(csv.DictReader(open(R + 'mapa.csv')))
produtos = sorted(set(r['NOME'] for r in mapa))
if a.produtos:
    produtos = [p for p in produtos if p in a.produtos.split(',')]
pular = set(a.pular.split(',')) if a.pular else set()
centralizados = sorted(set(r['NOME'] for r in mapa if r['lado'] == 'frente' and r['cor'] in CORES
                           and r['arquivo_estampa'].strip().upper() != 'LISO'
                           and abs(float(r['centro_x_rel'] or 0)) < 0.1))
if a.sem_frente_centralizada:
    pular |= set(centralizados)

tarefas = []
for p in produtos:
    if p in pular:
        continue
    for c in sorted(set(r['cor'] for r in mapa if r['NOME'] == p and r['cor'] in CORES)):
        cn, cod = CORES[c]
        finais = [os.path.join(a.saida, f'PALL-{p}-{cod}_{nn}.png') for nn in NUM.values()]
        if all(os.path.exists(f) for f in finais):
            continue
        tarefas.append((p, cn, cod))

print(f'{len(tarefas)} tarefas ({len(tarefas) * 4} fotos), {a.workers} ao mesmo tempo. '
      f'Fora (frente centralizada): {len(centralizados) if a.sem_frente_centralizada else 0}', flush=True)
json.dump(dict(frente_centralizada_pulados=centralizados if a.sem_frente_centralizada else []),
          open(os.path.join(a.saida, '_pulados.json'), 'w'), indent=1)


def rodar(t):
    p, cn, cod = t
    tmp = os.path.join(a.saida, f'_tmp_{p}_{cn}')
    os.makedirs(tmp, exist_ok=True)
    env = dict(os.environ, SAIDA_V31=tmp, INTEGRA='1', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
    env.pop('ACABAMENTO', None)                        # v3.2 aprovada
    fotos = ','.join(f'{cn}-{v}' for v in NUM)
    r = subprocess.run([sys.executable, os.path.join(AQUI, 'amostra_v31.py'), p, fotos],
                       env=env, capture_output=True, text=True)
    reg_arq = os.path.join(tmp, f'registro_{p}.json')
    reg = json.load(open(reg_arq)) if os.path.exists(reg_arq) else {}
    prob = [] if r.returncode == 0 else ['erro: ' + r.stderr[-600:]]
    for v, nn in NUM.items():
        n = f'{cn}-{v}'
        i = reg.get(n)
        if not i or not i.get('gerada'):
            prob.append(f'{n}: não gerada {i.get("problemas") if i else ""}')
        elif i.get('pixels_alterados_fora_da_tinta', 0) != 0:
            prob.append(f'{n}: {i["pixels_alterados_fora_da_tinta"]} px fora da tinta')
        else:
            shutil.move(os.path.join(tmp, f'{p}-{n}.png'), os.path.join(a.saida, f'PALL-{p}-{cod}_{nn}.png'))
    shutil.rmtree(tmp, ignore_errors=True)
    return t, prob, reg


rel_arq = os.path.join(a.saida, '_relatorio_modelos.json')
rel = json.load(open(rel_arq)) if os.path.exists(rel_arq) else {}
t0 = time.time()
with ThreadPoolExecutor(a.workers) as ex:
    futs = [ex.submit(rodar, t) for t in tarefas]
    for i, f in enumerate(as_completed(futs), 1):
        (p, cn, cod), prob, reg = f.result()
        rel[f'{p}-{cod}'] = dict(ok=not prob, problemas=prob, registro=reg)
        json.dump(rel, open(rel_arq, 'w'), indent=1, ensure_ascii=False)
        dt = time.time() - t0
        print(f'[{i}/{len(tarefas)}] {p}-{cod} {"OK" if not prob else prob} '
              f'- faltam ~{dt / i * (len(tarefas) - i) / 60:.0f} min', flush=True)
print('FIM', flush=True)
