"""Sobe os mockups padrão (01-03) do zip do Google Drive para branches públicos do GitHub, em lotes,
sem alterar nenhum byte (PNG original). Gera dados/mockups_drive_urls.json: nome -> URL raw."""
import zipfile, os, json, subprocess, shutil, sys
Z = '/tmp/claude-0/oficiais_dl/oficiais.zip'; PFX = 'CAMISETAS MOCKUPS FINAIS/'
OUT = '/home/user/logo/automacao-estampas/shopify/mockups_drive_urls.json'
REPO = 'https://github.com/efolettoe-ux/logo'
LOTE_MB = 550
z = zipfile.ZipFile(Z)
infos = [i for i in z.infolist() if i.filename.startswith(PFX) and i.filename.endswith('.png')
         and '/_fora-do-padrao/' not in i.filename and not i.filename.startswith('__')]
prior = sys.argv[1].split(',') if len(sys.argv) > 1 else []
infos.sort(key=lambda i: (0 if any(f'PALL-{p}-' in i.filename for p in prior) else 1, i.filename))
urls = json.load(open(OUT)) if os.path.exists(OUT) else {}
infos = [i for i in infos if os.path.basename(i.filename) not in urls]
lotes, cur, tam = [], [], 0
for i in infos:
    cur.append(i); tam += i.file_size
    if tam > LOTE_MB * 1e6: lotes.append(cur); cur, tam = [], 0
if cur: lotes.append(cur)
n0 = len([k for k in set(v.split('/')[5] for v in urls.values())]) if urls else 0
for k, lote in enumerate(lotes, n0 + 1):
    br = f'mockups-drive-lote-{k:02d}'
    T = f'/tmp/claude-0/push_lote'; shutil.rmtree(T, ignore_errors=True); os.makedirs(T)
    for i in lote:
        open(f'{T}/{os.path.basename(i.filename)}', 'wb').write(z.read(i))
    g = lambda *a: subprocess.run(['git', *a], cwd=T, check=True, capture_output=True, text=True)
    g('init', '-q'); g('checkout', '-q', '-b', br); g('config', 'user.name', 'Claude'); g('config', 'user.email', 'noreply@anthropic.com')
    g('add', '-A'); g('commit', '-q', '-m', f'Mockups padrão 01-03 do Google Drive (lote {k}, PNG originais)\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_015dR8M9wZ7z7a7xaM1gVKNK')
    g('remote', 'add', 'origin', REPO)
    for t in range(4):
        r = subprocess.run(['git', 'push', '-q', 'origin', br], cwd=T, capture_output=True, text=True)
        if r.returncode == 0: break
    else:
        print('FALHA push', br, r.stderr[-300:], flush=True); sys.exit(1)
    for i in lote:
        n = os.path.basename(i.filename)
        urls[n] = f'https://raw.githubusercontent.com/efolettoe-ux/logo/{br}/{n}'
    json.dump(urls, open(OUT, 'w'), indent=0)
    shutil.rmtree(T, ignore_errors=True)
    print(f'{br}: {len(lote)} arquivos, total {len(urls)}', flush=True)
print('FIM', len(urls), flush=True)
