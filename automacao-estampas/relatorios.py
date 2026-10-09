"""Relatórios: diagnóstico (HTML + CSV), folha de contato, antes x depois.

Páginas HTML simples, offline, em português, que abrem com dois cliques no Mac.
"""
from __future__ import annotations

import html
import os
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

from catalogo import LinhaDiagnostico, escrever_csv_dicts

CSS = """
:root{--fundo:#f6f5f2;--card:#fff;--texto:#1d1d1f;--sub:#6e6e73;--linha:#e3e1dc;--ok:#2e7d32;--aviso:#b26a00;--erro:#c62828}
@media (prefers-color-scheme: dark){:root{--fundo:#161616;--card:#1f1f1f;--texto:#f2f2f2;--sub:#a0a0a0;--linha:#333;}}
*{box-sizing:border-box}body{margin:0;padding:24px 16px;background:var(--fundo);color:var(--texto);
font:15px/1.45 -apple-system,BlinkMacSystemFont,"Helvetica Neue",Arial,sans-serif}
h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:28px 0 8px}.sub{color:var(--sub)}
.cards{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0}.card{background:var(--card);border:1px solid var(--linha);
border-radius:10px;padding:10px 14px;min-width:120px}.card b{display:block;font-size:22px}
table{border-collapse:collapse;width:100%;background:var(--card);font-size:13px}th,td{border-bottom:1px solid var(--linha);
padding:6px 8px;text-align:left;vertical-align:top}th{position:sticky;top:0;background:var(--card)}
.ok{color:var(--ok)}.aviso{color:var(--aviso)}.erro{color:var(--erro)}.tag{display:inline-block;padding:1px 7px;border-radius:9px;
border:1px solid currentColor;font-size:12px}input{padding:7px 10px;font-size:14px;width:100%;max-width:360px;margin:8px 0;
border:1px solid var(--linha);border-radius:8px;background:var(--card);color:var(--texto)}
.par{display:grid;grid-template-columns:1fr 1fr;gap:8px;background:var(--card);border:1px solid var(--linha);border-radius:10px;
padding:10px;margin:10px 0}.par img{width:100%;height:auto;border-radius:6px;background:#eee}.par .tit{grid-column:1/3;font-weight:600}
.wrap{max-width:1200px;margin:0 auto;overflow-x:auto}
"""

FILTRO_JS = """
<script>
function filtrar(v){v=v.toLowerCase();document.querySelectorAll('[data-busca]').forEach(function(el){
el.style.display = el.getAttribute('data-busca').indexOf(v)>=0 ? '' : 'none';});}
function soProblemas(c){document.querySelectorAll('[data-grav]').forEach(function(el){
el.style.display = (!c || el.getAttribute('data-grav')!=='ok') ? '' : 'none';});}
</script>
"""


def _pagina(titulo: str, corpo: str) -> str:
    return (f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(titulo)}</title>"
            f"<style>{CSS}</style>{FILTRO_JS}</head><body><div class='wrap'>{corpo}</div></body></html>")


# ---------------------------------------------------------------------------
# Diagnóstico
# ---------------------------------------------------------------------------

COLUNAS_DIAG = ["handle", "NOME", "titulo", "status", "cores", "lados_descricao", "n_imagens", "imagens_por_cor",
                "estado_nomes", "gravidade", "problemas"]


def escrever_diagnostico(linhas: List[LinhaDiagnostico], resumo: Dict[str, int], destino_html: Path,
                         destino_csv: Path) -> None:
    dicts = [{"handle": l.handle, "NOME": l.nome, "titulo": l.titulo, "status": l.status,
              "cores": " | ".join(l.cores), "lados_descricao": "+".join(l.lados_descricao) or "nenhum",
              "n_imagens": l.n_imagens, "imagens_por_cor": l.imagens_por_cor, "estado_nomes": l.estado_nomes,
              "gravidade": l.gravidade, "problemas": " ; ".join(l.problemas)} for l in linhas]
    escrever_csv_dicts(destino_csv, COLUNAS_DIAG, dicts)
    nomes = {
        "produtos": "camisetas no CSV", "ativos_no_lote": "entram no lote", "teste_ou_inativos": "teste / inativas",
        "azul_marinho_minusculo": "'Azul marinho' minúsculo", "so_costas": "só costas", "frente_e_costas": "frente + costas",
        "so_frente": "só frente", "sem_lado": "descrição sem lado", "nomes_aleatorios": "nomes de imagem aleatórios",
        "imagens": "imagens atuais", "com_problema": "com algum aviso",
    }
    cards = "".join(f"<div class='card'><b>{resumo.get(k, 0)}</b>{html.escape(v)}</div>" for k, v in nomes.items())
    cont = Counter(c for l in linhas for c in l.cores)
    cores = ", ".join(f"{html.escape(c)}: {n}" for c, n in cont.most_common())
    linhas_html = []
    for l in linhas:
        busca = html.escape(f"{l.handle} {l.nome} {' '.join(l.problemas)}".lower())
        probs = "<br>".join(html.escape(p) for p in l.problemas) or "<span class='ok'>ok</span>"
        linhas_html.append(
            f"<tr data-busca='{busca}' data-grav='{l.gravidade}'><td><b>{html.escape(l.nome)}</b><br>"
            f"<span class='sub'>{html.escape(l.handle)}</span></td><td>{html.escape(', '.join(l.cores))}</td>"
            f"<td>{html.escape('+'.join(l.lados_descricao) or '—')}</td><td>{l.n_imagens}</td>"
            f"<td>{html.escape(l.estado_nomes)}</td><td><span class='tag {l.gravidade}'>{l.gravidade}</span></td>"
            f"<td>{probs}</td></tr>")
    corpo = (f"<h1>Diagnóstico das camisetas</h1><p class='sub'>Lido só do CSV do Shopify. Nada foi alterado na loja.</p>"
             f"<div class='cards'>{cards}</div><p class='sub'>Cores: {cores}</p>"
             f"<input placeholder='Buscar produto ou problema…' oninput='filtrar(this.value)'> "
             f"<label><input type='checkbox' style='width:auto' onchange='soProblemas(this.checked)'> só com aviso</label>"
             f"<table><thead><tr><th>Produto</th><th>Cores</th><th>Estampa (descrição)</th><th>Imagens</th>"
             f"<th>Nomes</th><th>Situação</th><th>Observações</th></tr></thead><tbody>{''.join(linhas_html)}</tbody></table>")
    destino_html.write_text(_pagina("Diagnóstico PALLACIO", corpo), encoding="utf-8")


# ---------------------------------------------------------------------------
# Folha de contato
# ---------------------------------------------------------------------------

def _fonte(tam: int):
    for nome in ("/System/Library/Fonts/Helvetica.ttc", "/Library/Fonts/Arial.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(nome, tam)
        except Exception:
            continue
    return ImageFont.load_default()


def folha_contato(itens: Sequence[Tuple[str, str]], destino: Path, miniatura: int = 200, por_folha: int = 240,
                  colunas: int = 9) -> List[Path]:
    """itens = [(caminho_imagem, legenda)]. Gera destino.jpg (e destino-2.jpg... se passar de por_folha)."""
    saidas = []
    fonte = _fonte(max(10, miniatura // 16))
    leg_h = max(16, miniatura // 8)
    for k in range(0, max(1, len(itens)), por_folha):
        lote = list(itens[k:k + por_folha])
        if not lote:
            break
        cols = min(colunas, len(lote))
        linhas = (len(lote) + cols - 1) // cols
        folha = Image.new("RGB", (cols * miniatura, linhas * (miniatura + leg_h)), (255, 255, 255))
        d = ImageDraw.Draw(folha)
        for i, (cam, leg) in enumerate(lote):
            x, y = (i % cols) * miniatura, (i // cols) * (miniatura + leg_h)
            try:
                with Image.open(cam) as im:
                    im.draft("RGB", (miniatura, miniatura))
                    t = im.convert("RGB")
                    t.thumbnail((miniatura - 4, miniatura - 4))
                folha.paste(t, (x + (miniatura - t.size[0]) // 2, y + (miniatura - t.size[1]) // 2))
            except Exception:
                d.text((x + 6, y + 6), "erro ao abrir", fill=(200, 0, 0), font=fonte)
            d.text((x + 4, y + miniatura + 2), leg[:34], fill=(40, 40, 40), font=fonte)
        n = k // por_folha
        p = destino if n == 0 else destino.with_name(f"{destino.stem}-{n + 1}{destino.suffix}")
        folha.save(p, quality=85)
        saidas.append(p)
    return saidas


# ---------------------------------------------------------------------------
# Antes x depois
# ---------------------------------------------------------------------------

def antes_depois(pares: Sequence[dict], destino: Path, pendencias: Optional[Dict[str, List[str]]] = None) -> None:
    """Página de conferência agrupada por produto.

    pares: [{"produto", "titulo", "antes" (caminho ou ''), "depois" (caminho), "obs"}].
    pendencias: produto -> lista de textos (lados sem arte, artes para revisar...), mostradas no topo do grupo.
    As fotos atuais são copiadas (miniatura JPEG) para a pasta antes_depois_fotos/ ao lado da página:
    assim a página continua funcionando se a pasta do projeto mudar de lugar.
    """
    import hashlib
    base = destino.parent.resolve()
    pasta_fotos = base / (destino.stem + "_fotos")
    pendencias = pendencias or {}

    def rel(c):
        try:
            return html.escape(Path(os.path.relpath(Path(c).resolve(), base)).as_posix())
        except ValueError:
            return html.escape(Path(c).resolve().as_uri())

    def copia_local(c: str) -> str:
        if not c or not Path(c).exists():
            return ""
        p = Path(c).resolve()
        try:
            p.relative_to(base)
            return rel(p)  # já está dentro do projeto
        except ValueError:
            pass
        nome = hashlib.sha1(str(p).encode("utf-8")).hexdigest()[:16] + ".jpg"
        alvo = pasta_fotos / nome
        if not alvo.exists():
            try:
                pasta_fotos.mkdir(parents=True, exist_ok=True)
                with Image.open(p) as im:
                    im = im.convert("RGB")
                    im.thumbnail((900, 900))
                    im.save(alvo, quality=85)
            except Exception:
                return ""
        return rel(alvo)

    grupos: Dict[str, List[dict]] = {}
    for p in pares:
        grupos.setdefault(p.get("produto") or p["titulo"].split(" — ")[0], []).append(p)
    for prod in pendencias:
        grupos.setdefault(prod, [])
    com_foto = {g for g, ps in grupos.items() if any(p.get("antes") for p in ps)}
    ordem = sorted(grupos, key=lambda g: (g not in com_foto, g))
    blocos = []
    for g in ordem:
        ps = grupos[g]
        pend = pendencias.get(g, [])
        cartoes = []
        for p in ps:
            antes = copia_local(p.get("antes", ""))
            antes_html = (f"<img loading='lazy' src='{antes}' alt='foto atual'>" if antes
                          else "<div class='vazio'>sem foto atual</div>")
            cartoes.append(f"<div class='par2'><div class='tit2'>{html.escape(p['titulo'].split(' — ', 1)[-1])}"
                           f" <span class='sub'>{html.escape(p.get('obs', ''))}</span></div>"
                           f"{antes_html}<img loading='lazy' src='{rel(p['depois'])}' alt='nova'></div>")
        pend_html = ("<ul class='pend'>" + "".join(f"<li>{html.escape(t)}</li>" for t in pend) + "</ul>") if pend else ""
        busca = html.escape(g.lower())
        tag_pend = " <span class='tag aviso'>pendências</span>" if pend else ""
        blocos.append(f"<section class='grupo' data-busca='{busca}' data-foto='{'1' if g in com_foto else '0'}' "
                      f"data-pend='{'1' if pend else '0'}'><h2>{html.escape(g)} "
                      f"<span class='sub'>{len(ps)} imagem(ns){' · sem foto atual' if g not in com_foto else ''}</span>"
                      f"{tag_pend}</h2>{pend_html}"
                      f"<div class='grade'>{''.join(cartoes)}</div></section>")
    css = ("<style>.grade{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:10px}"
           ".par2{display:grid;grid-template-columns:1fr 1fr;gap:6px;background:var(--card);border:1px solid var(--linha);"
           "border-radius:10px;padding:8px}.par2 img{width:100%;height:auto;border-radius:6px;background:#eee}"
           ".tit2{grid-column:1/3;font-size:13px;font-weight:600}.vazio{display:flex;align-items:center;justify-content:center;"
           "text-align:center;color:var(--sub);font-size:12px;border:1px dashed var(--linha);border-radius:6px;min-height:120px}"
           ".pend{margin:4px 0 10px;padding-left:20px;color:var(--aviso);font-size:13px}.grupo{margin-bottom:22px}"
           "label{margin-right:14px;font-size:14px}</style>")
    js = ("<script>function aplicar(){var v=document.getElementById('b').value.toLowerCase(),"
          "f=document.getElementById('f').checked,p=document.getElementById('p').checked;"
          "document.querySelectorAll('.grupo').forEach(function(el){var ok=el.getAttribute('data-busca').indexOf(v)>=0"
          "&&(!f||el.getAttribute('data-foto')==='1')&&(!p||el.getAttribute('data-pend')==='1');"
          "el.style.display=ok?'':'none';});}</script>")
    n_pend = sum(1 for g in grupos if pendencias.get(g))
    corpo = (f"{css}{js}<h1>Antes x depois</h1><p class='sub'>Em cada par: à esquerda a foto atual da loja, à direita "
             f"a imagem nova. Confira tamanho, posição e cor da estampa. {len(grupos)} produtos; {len(com_foto)} com "
             f"foto atual; {n_pend} com pendências (lado sem arte ou arte para revisar — essas imagens não foram "
             f"geradas).</p>"
             f"<input id='b' placeholder='Buscar produto…' oninput='aplicar()'> "
             f"<label><input type='checkbox' id='f' onchange='aplicar()' style='width:auto'> só com foto atual</label>"
             f"<label><input type='checkbox' id='p' onchange='aplicar()' style='width:auto'> só com pendências</label>"
             + "".join(blocos))
    destino.write_text(_pagina("Antes x depois PALLACIO", corpo), encoding="utf-8")
