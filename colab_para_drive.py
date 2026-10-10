# PALLACIO: copia todas as imagens finais do GitHub para UMA pasta do Google Drive (sem subpastas).
# Cole esta célula no Google Colab (colab.research.google.com > Novo notebook) e aperte ▶.
# Os arquivos vão de nuvem para nuvem, byte a byte (sem recompressão, sem usar o seu computador).
from google.colab import drive
drive.mount('/content/drive')
import os, csv, io, zipfile, shutil, urllib.request

PASTA = '/content/drive/MyDrive/PALLACIO MOCKUPS FINAIS'      # pasta única no seu Drive
REPO = 'efolettoe-ux/logo'
os.makedirs(PASTA, exist_ok=True)

mapa_txt = urllib.request.urlopen(f'https://raw.githubusercontent.com/{REPO}/drive-organizacao/mapa_drive.csv').read().decode()
mapa = list(csv.DictReader(io.StringIO(mapa_txt)))
print(len(mapa), 'imagens para copiar')

feitos = 0
for branch in sorted({r['branch'] for r in mapa}):
    zip_local = f'/content/{branch}.zip'
    print('baixando', branch, '...')
    urllib.request.urlretrieve(f'https://github.com/{REPO}/archive/refs/heads/{branch}.zip', zip_local)
    with zipfile.ZipFile(zip_local) as zf:
        por_nome = {os.path.basename(n): n for n in zf.namelist() if not n.endswith('/')}
        for r in (r for r in mapa if r['branch'] == branch):
            destino = os.path.join(PASTA, r['destino'])
            if os.path.exists(destino):
                feitos += 1
                continue
            with zf.open(por_nome[r['origem']]) as src, open(destino, 'wb') as out:
                shutil.copyfileobj(src, out)
            feitos += 1
    os.remove(zip_local)
    print('  ok:', feitos, 'de', len(mapa))

total = len([f for f in os.listdir(PASTA) if f.endswith('.png')])
print('PRONTO:', total, 'imagens em', PASTA)
