#!/usr/bin/env python3
"""PALLACIO — aplica as estampas nos mockups lisos das camisetas.

Uso:  python3 pallacio.py <comando> [opções]
Ordem: diagnostico -> baixar -> analisar -> casar -> (revisar) -> estampar --limite 3 --previa -> estampar
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

if sys.version_info < (3, 9):
    sys.exit("Este programa precisa do Python 3.9 ou mais novo. Veja o README (seção 'Instalar o Python').")

try:
    import numpy  # noqa: F401
    from PIL import Image  # noqa: F401
except ImportError:
    sys.exit("Faltam bibliotecas. No Terminal, rode:\n    pip3 install pillow numpy\n"
             "e depois tente de novo.")

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

from catalogo import ErroUsuario, Projeto, carregar_config, diagnosticar, ler_catalogo, ler_csv_dicts, ler_mapa, resumo_diagnostico  # noqa: E402


def _projeto(args) -> Projeto:
    raiz = Path(args.pasta).expanduser().resolve() if getattr(args, "pasta", None) else Path.cwd()
    cfg_path = raiz / "config.json"
    novo = not cfg_path.exists()
    cfg = carregar_config(cfg_path)
    cal = raiz / "calibracao.json"
    if cal.exists():
        import json
        from catalogo import _mesclar
        try:
            cfg = _mesclar(cfg, json.loads(cal.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            raise ErroUsuario("calibracao.json está com erro; baixe de novo pelo calibrador.")
    if novo:
        print(f"Criei {cfg_path.name} com os valores padrão (pode editar depois).")
    return Projeto(raiz, cfg, getattr(args, "tipo", "camiseta") or "camiseta")


def _lista(valores):
    out = []
    for v in valores or []:
        out += [x.strip() for x in v.split(",") if x.strip()]
    return out


def _barra(i: int, n: int, texto: str = "") -> None:
    larg = 28
    feito = int(larg * i / max(n, 1))
    sys.stdout.write(f"\r  [{'#' * feito}{'.' * (larg - feito)}] {i}/{n} {texto[:40]:<40}")
    sys.stdout.flush()
    if i >= n:
        sys.stdout.write("\n")


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------

def cmd_diagnostico(args) -> None:
    from mockups import achar_pasta_mockups, descobrir_mockups
    from relatorios import escrever_diagnostico
    proj = _projeto(args)
    csv_path = proj.caminho_csv(args.csv)
    produtos = ler_catalogo(csv_path, proj.cfg, proj.tipo, incluir_excluidos=True)
    pasta_mk = achar_pasta_mockups(proj.raiz, proj.cfg, proj.tipo, args.mockups)
    cores_mk = descobrir_mockups(pasta_mk, proj.cfg).cores_completas() if pasta_mk else None
    linhas = diagnosticar(produtos, proj.cfg, cores_mk)
    resumo = resumo_diagnostico(linhas, produtos)
    escrever_diagnostico(linhas, resumo, proj.arquivo("diagnostico_html"), proj.arquivo("diagnostico_csv"))
    print(f"Li {csv_path.name}: {resumo['produtos']} camisetas ({resumo['ativos_no_lote']} entram no lote, "
          f"{resumo['teste_ou_inativos']} de teste/inativas).")
    print(f"  só costas: {resumo['so_costas']} | frente+costas: {resumo['frente_e_costas']} | só frente: {resumo['so_frente']}")
    print(f"  'Azul marinho' com m minúsculo: {resumo['azul_marinho_minusculo']} (vou tratar como Azul Marinho)")
    print(f"  produtos com algum aviso: {resumo['com_problema']}")
    if pasta_mk is None:
        print("  (não achei a pasta de mockups; coloque os PNGs lisos em 'mockups/' para conferir as cores)")
    print(f"Abra o relatório: {proj.arquivo('diagnostico_html')}")


def cmd_baixar(args) -> None:
    proj = _projeto(args)
    try:
        import baixar
    except ImportError:
        raise ErroUsuario("Falta o arquivo baixar.py ao lado do pallacio.py (baixe o programa de novo).")
    baixar.comando(proj, args)


def cmd_analisar(args) -> None:
    import analisar
    proj = _projeto(args)
    produtos = ler_catalogo(proj.caminho_csv(args.csv), proj.cfg, proj.tipo)
    filtro = {x.upper() for x in _lista(args.produto)}
    if filtro:
        produtos = [p for p in produtos if p.nome in filtro or p.handle.upper() in filtro]
    extra = Path(args.fotos).expanduser() if args.fotos else None
    if extra is None:
        from casamento import achar_raiz_arquivos
        raiz_arq = achar_raiz_arquivos(proj)
        cand = raiz_arq / proj.cfg["casar"].get("pasta_fotos_extra", "") if raiz_arq else None
        if cand is not None and proj.cfg["casar"].get("pasta_fotos_extra") and cand.is_dir():
            extra = cand
            print(f"Também vou medir as fotos de {cand} (uma subpasta por produto).")
    pasta_an = proj.pasta("analise", criar=True)
    t0 = time.time()
    print("Analisando as fotos atuais (tronco, cor, lado e estampa)...")
    linhas = analisar.analisar(produtos, proj.pasta("atuais"), pasta_an, proj.cfg, extra, args.workers,
                               progresso=lambda i, n, l: _barra(i, n, l.get("NOME", "")))
    if not linhas:
        raise ErroUsuario("Não achei fotos atuais. Rode antes: python3 pallacio.py baixar "
                          "(ou use --fotos PASTA com uma subpasta por produto).")
    analisar.salvar(linhas, proj.arquivo("analise_csv"))
    rev = sum(1 for l in linhas if l.get("revisar") == "sim")
    print(f"{len(linhas)} fotos analisadas em {time.time() - t0:.0f}s ({rev} para revisar). "
          f"Resultado: {proj.arquivo('analise_csv')}")


def cmd_casar(args) -> None:
    proj = _projeto(args)
    try:
        import casamento
    except ImportError:
        raise ErroUsuario("Falta o arquivo casamento.py ao lado do pallacio.py (baixe o programa de novo).")
    casamento.comando(proj, args)


def cmd_extrair(args) -> None:
    proj = _projeto(args)
    from extrair import extrair
    if not (proj.raiz / "analise.csv").exists():
        raise ErroUsuario("Rode antes: python3 pallacio.py baixar e python3 pallacio.py analisar")
    prods = [x.strip() for v in (args.produto or []) for x in v.split(",") if x.strip()]
    r = extrair(proj.raiz, prods or None, args.fator, args.incluir_revisar)
    print(f"Estampas tiradas das fotos da loja: {r['extraidas']} (em estampas_da_loja/). "
          f"Sem foto com estampa: {r['sem_foto']}. Agora rode o estampar.")


def cmd_estampar(args) -> None:
    import estampar as E
    from catalogo import escrever_csv_dicts
    from mockups import achar_pasta_mockups, descobrir_mockups
    from relatorios import antes_depois, folha_contato
    proj = _projeto(args)
    cfg = proj.cfg
    pasta_mk = achar_pasta_mockups(proj.raiz, cfg, proj.tipo, args.mockups)
    if pasta_mk is None:
        raise ErroUsuario("Não achei a pasta dos mockups lisos. Coloque os PNGs (preta-frente.png, preta-costas.png, "
                          "preta-close-costas.png...) numa pasta 'mockups' ao lado do programa, ou use --mockups PASTA.")
    mk = descobrir_mockups(pasta_mk, cfg)
    if not mk.mockups:
        raise ErroUsuario(f"A pasta {pasta_mk} não tem mockups com cor e vista no nome (ex.: preta-costas.png).")
    mapa_path = Path(args.mapa).expanduser() if args.mapa else proj.arquivo("mapa_csv")
    if not args.mapa and not mapa_path.exists() and (AQUI / "dados" / "mapa.csv").exists():
        mapa_path = AQUI / "dados" / "mapa.csv"
        print(f"Ainda não há mapa.csv nesta pasta; uso o mapa que vem com o programa ({mapa_path}).")
    mapa = ler_mapa(mapa_path, cfg)
    if not mapa:
        raise ErroUsuario(f"O {mapa_path.name} está vazio ou não existe. Rode antes: python3 pallacio.py casar")
    produtos = None
    try:
        produtos = ler_catalogo(proj.caminho_csv(args.csv), cfg, proj.tipo)
    except ErroUsuario:
        print("Aviso: sem o CSV do Shopify; uso só os produtos e cores do mapa.csv.")
    analise = ler_csv_dicts(proj.arquivo("analise_csv"))
    tarefas = E.planejar(proj, mapa, mk, produtos, _lista(args.produto), _lista(args.cor), args.limite,
                         args.forcar, args.previa, analise, incluir_revisar=args.incluir_revisar)
    n_img = sum(1 for t in tarefas for v in t.vistas if not v.status)
    print(f"Mockups: {pasta_mk.name} ({len(mk.mockups)} arquivos"
          + (f"; desativadas: {', '.join(mk.cores_desativadas)}" if mk.cores_desativadas else "") + ")")
    print(f"Vou gerar {n_img} imagens ({'prévia rápida' if args.previa else 'resolução final'}) "
          f"com {args.workers} processo(s)...")
    t0 = time.time()
    tarefas = E.executar(tarefas, cfg, proj.raiz, args.previa, args.workers,
                         progresso=lambda i, n, t: _barra(i, n, f"{t.nome} {t.codigo}"))
    linhas = E.linhas_relatorio(tarefas)
    escrever_csv_dicts(proj.arquivo("relatorio_csv"), E.COLUNAS_RELATORIO, linhas)
    from collections import Counter
    cont = Counter(l["status"] for l in linhas)
    print(f"Pronto em {time.time() - t0:.0f}s: " + ", ".join(f"{k}: {v}" for k, v in sorted(cont.items())))
    feitas = [(v.arquivo_png, f"{t.nome} {t.codigo} {v.numero:02d}") for t in tarefas for v in t.vistas
              if v.status in ("ok", "liso", "pulado") and Path(v.arquivo_png).exists()]
    if feitas:
        fc = folha_contato(feitas, proj.arquivo("folha_contato"), int(cfg["saida"].get("contato_miniatura", 200)),
                           int(cfg["saida"].get("contato_por_folha", 240)))
        print(f"Folha de contato: {', '.join(p.name for p in fc)}")
        pares = _pares_antes_depois(tarefas, analise)
        antes_depois(pares, proj.arquivo("antes_depois_html"), _pendencias(tarefas))
        print(f"Antes x depois: {proj.arquivo('antes_depois_html').name}")
    if cont.get("revisar"):
        print(f"Atenção: {cont['revisar']} imagem(ns) NÃO foram geradas porque a arte precisa de revisão "
              "(status revisar no relatorio.csv). Confira no revisao.html; se a arte estiver certa, troque "
              "revisar para nao no mapa.csv e rode de novo.")
    if cont.get("sem_estampa"):
        print(f"Faltam artes: {cont['sem_estampa']} lado(s)/cor(es) sem arquivo (status sem_estampa no relatorio.csv).")
    if cont.get("erro"):
        print(f"Atenção: {cont['erro']} imagem(ns) com erro — veja a coluna observacao em relatorio.csv")
    print(f"Relatório: {proj.arquivo('relatorio_csv')}")


def _pares_antes_depois(tarefas, analise):
    fotos = {}
    for l in analise:
        if l.get("lado") and l.get("cor") and l.get("arquivo"):
            fotos.setdefault((l["handle"], l["cor"], l["lado"]), l["arquivo"])
    pares = []
    for t in tarefas:
        for v in t.vistas:
            if v.status in ("ok", "liso", "pulado") and Path(v.arquivo_png).exists():
                lado = "costas" if v.vista == "close-costas" else v.vista
                antes = fotos.get((t.handle, t.cor, lado), "")
                pares.append({"produto": t.nome, "titulo": f"{t.nome} — {t.cor} — {v.numero:02d} {v.vista}",
                              "antes": antes if v.vista != "close-costas" else "",
                              "depois": v.arquivo_web if v.arquivo_web and Path(v.arquivo_web).exists() else v.arquivo_png,
                              "obs": f"geometria: {v.origem_geometria}" if v.estampa else "lado liso"})
    return pares


def _pendencias(tarefas):
    """produto -> textos do que NÃO foi gerado (falta arte, revisar, erro)."""
    nomes = {"sem_estampa": "falta a arte", "revisar": "arte para revisar", "erro": "erro", "sem_mockup": "sem mockup"}
    out = {}
    for t in tarefas:
        if t.status in nomes:
            out.setdefault(t.nome, []).append(f"{t.cor}: {nomes[t.status]} — {t.observacao}")
        for v in t.vistas:
            if v.status in nomes:
                out.setdefault(t.nome, []).append(f"{t.cor} {v.numero:02d} {v.vista}: {nomes[v.status]} — "
                                                  f"{v.observacao.split(' [')[0]}")
    return out


def cmd_calibrador(args) -> None:
    p = AQUI / "calibrador.html"
    print(f"Abra no navegador (dois cliques): {p}")
    print("Depois de ajustar, clique em 'Baixar ajustes' e coloque o arquivo calibracao.json na pasta do projeto.")
    try:
        import webbrowser
        webbrowser.open(p.as_uri())
    except Exception:
        pass


# ---------------------------------------------------------------------------

def montar_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python3 pallacio.py",
        description="PALLACIO — aplica as estampas nos mockups lisos das camisetas, no padrão da loja.",
        epilog="Ordem recomendada: diagnostico -> baixar -> analisar -> casar -> abrir revisao.html "
               "-> estampar --limite 3 --previa -> estampar",
    )
    sub = ap.add_subparsers(dest="comando", metavar="<comando>")

    def comum(p):
        p.add_argument("--pasta", help="pasta do projeto (padrão: a pasta atual do Terminal)")
        p.add_argument("--csv", help="CSV exportado do Shopify (padrão: products_export*.csv da pasta)")
        p.add_argument("--tipo", default="camiseta", help="camiseta (padrão) ou moletom")

    p = sub.add_parser("diagnostico", help="relatório do CSV (cores, lados, imagens, problemas)")
    comum(p)
    p.add_argument("--mockups", help="pasta dos mockups lisos")
    p.set_defaults(func=cmd_diagnostico)

    p = sub.add_parser("baixar", help="baixa as fotos atuais da loja para atuais/")
    comum(p)
    p.add_argument("--workers", type=int, default=8, help="downloads ao mesmo tempo (padrão 8)")
    p.add_argument("--produto", action="append", help="só estes produtos (NOME; pode repetir ou separar por vírgula)")
    p.add_argument("--largura", type=int, help="largura pedida ao Shopify (padrão 1500)")
    p.set_defaults(func=cmd_baixar)

    p = sub.add_parser("analisar", help="mede cor, lado, posição e tamanho da estampa nas fotos atuais")
    comum(p)
    p.add_argument("--fotos", help="pasta extra com uma subpasta por produto (ex.: 'JA FOI')")
    p.add_argument("--produto", action="append", help="só estes produtos (NOME)")
    p.add_argument("--workers", type=int, default=4, help="processos em paralelo (padrão 4)")
    p.set_defaults(func=cmd_analisar)

    p = sub.add_parser("casar", help="acha a estampa de cada produto/cor/lado e preenche o mapa.csv")
    comum(p)
    p.add_argument("--arquivos", help="pasta que contém 'CAMISETAS 100%%', 'NOVAS', 'MATERIAL QUALITY 100%%'... "
                                      "(padrão: procura sozinho)")
    p.add_argument("--estampas", action="append", help="pasta(s) extra com artes, relativas à pasta dos arquivos")
    p.add_argument("--inventario", help="inventário das artes (padrão: dados/inventario.csv do programa)")
    p.add_argument("--workers", type=int, default=4, help="processos em paralelo (padrão 4)")
    p.add_argument("--sem-miniaturas", action="store_true", help="mais rápido: prévia só das artes escolhidas")
    p.set_defaults(func=cmd_casar)

    p = sub.add_parser("extrair", help="tira a estampa das fotos da loja onde falta o arquivo da arte")
    comum(p)
    p.add_argument("--produto", action="append", help="só estes produtos (NOME; vírgula ou repetido)")
    p.add_argument("--fator", type=float, default=3.0, help="ampliação da estampa recortada (padrão 3)")
    p.add_argument("--incluir-revisar", action="store_true", help="também nas linhas marcadas revisar=sim")
    p.set_defaults(func=cmd_extrair)

    p = sub.add_parser("estampar", help="gera as imagens novas (saida/, saida_web/)")
    comum(p)
    p.add_argument("--mockups", help="pasta dos mockups lisos")
    p.add_argument("--mapa", help="mapa.csv a usar (padrão: mapa.csv da pasta)")
    p.add_argument("--limite", type=int, help="só os N primeiros produtos (para testar)")
    p.add_argument("--produto", action="append", help="só estes produtos (NOME; pode repetir ou separar por vírgula)")
    p.add_argument("--cor", action="append", help="só estas cores (Preta, Branca, 'Off White', 'Azul Marinho' ou PT/BR/OW/AZ)")
    p.add_argument("--forcar", action="store_true", help="refaz imagens que já existem")
    p.add_argument("--workers", type=int, default=max(1, min(4, (__import__('os').cpu_count() or 2) - 1)),
                   help="processos em paralelo (padrão: núcleos - 1, até 4)")
    p.add_argument("--previa", action="store_true", help="prévia rápida em baixa resolução (saida_previa/)")
    p.add_argument("--incluir-revisar", action="store_true",
                   help="gera também as artes marcadas revisar=sim no mapa.csv (só para conferir; o normal é "
                        "revisar e trocar para nao)")
    p.set_defaults(func=cmd_estampar)

    p = sub.add_parser("calibrador", help="abre o calibrador (ajuste fino do tronco e da estampa)")
    p.set_defaults(func=cmd_calibrador)
    return ap


def main(argv=None) -> int:
    ap = montar_parser()
    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return 1
    try:
        args.func(args)
    except ErroUsuario as e:
        print(f"\nErro: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrompido. Pode rodar de novo: o que já ficou pronto é pulado.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
