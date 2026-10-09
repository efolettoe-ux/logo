"""Comando analisar: mede cada foto atual da loja (cor do tecido, lado, posição e tamanho da estampa).

Entrada: atuais/{handle}/ (criada pelo baixar, arquivos com o mesmo nome do CDN do Shopify) ou uma pasta
no formato "JA FOI" (--pasta): uma subpasta por produto com o título ("CAPRESE T-SHIRT") e fotos
1.png..8.png — o número casa com o começo do nome no CDN ("4_c81e72de-....png").
Saída: analise.csv (COLUNAS_ANALISE) + recortes da estampa em analise/recortes/.
"""
from __future__ import annotations

import re
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from catalogo import (COLUNAS_ANALISE, ImagemLoja, Produto, escrever_csv_dicts, pistas_texto, sem_acentos)
from imagem import EXT_IMAGEM, analisar_imagem, carregar_imagem

LIMITE_PEITO = 0.40  # largura_rel abaixo disso = logo de peito (frente)


def _chave(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", sem_acentos(s).lower())


def listar_imagens(produtos: List[Produto], pasta_atuais: Path, pasta_extra: Optional[Path] = None
                   ) -> List[Tuple[Produto, Path, Optional[ImagemLoja]]]:
    """(produto, arquivo local, imagem da loja correspondente) para tudo que existir no disco."""
    out = []
    por_chave = {}
    for p in produtos:
        for k in {_chave(p.titulo), _chave(p.nome), _chave(p.handle)}:
            por_chave[k] = p
    for p in produtos:
        d = pasta_atuais / p.handle
        if d.is_dir():
            por_nome = {im.nome_arquivo: im for im in p.imagens}
            for arq in sorted(d.iterdir()):
                if arq.suffix.lower() in EXT_IMAGEM and not arq.name.startswith("."):
                    out.append((p, arq, por_nome.get(arq.name)))
    if pasta_extra and pasta_extra.is_dir():
        for sub in sorted(pasta_extra.iterdir()):
            if not sub.is_dir():
                continue
            p = por_chave.get(_chave(sub.name))
            if p is None:
                continue
            for arq in sorted(sub.iterdir()):
                if arq.suffix.lower() not in EXT_IMAGEM or arq.name.startswith("."):
                    continue
                im = next((i for i in p.imagens if i.nome_arquivo.split("_")[0] == arq.stem), None)
                out.append((p, arq, im))
    return out


def _uma(args) -> dict:
    p, arq, im, cfg, pasta_rec = args
    linha = {"handle": p.handle, "NOME": p.nome, "arquivo": str(arq), "url": im.url if im else "",
             "posicao": im.posicao if im else "", "alt": im.alt if im else ""}
    try:
        a = analisar_imagem(carregar_imagem(arq), cfg)
    except Exception as e:
        linha.update({"revisar": "sim", "observacao": f"erro: {e}"})
        return linha
    linha.update(a.para_linha())
    linha["cor"] = a.cor.nome
    if a.recorte is not None:
        destino = pasta_rec / p.handle / (arq.stem + "-estampa.jpg")
        destino.parent.mkdir(parents=True, exist_ok=True)
        a.recorte.save(destino, quality=88)
        linha["recorte"] = str(destino)
    return linha


def decidir_lados(linhas: List[dict], produtos: Dict[str, Produto], cfg: dict) -> None:
    """Lado de cada foto: palavra no nome/alt > tamanho da estampa > imagem da variante > decote."""
    grupos: Dict[Tuple[str, str], List[dict]] = {}
    for l in linhas:
        grupos.setdefault((l["handle"], l.get("cor", "")), []).append(l)
    for (h, cor), ls in grupos.items():
        p = produtos[h]
        for l in ls:
            pista = pistas_texto(Path(l["arquivo"]).name + " " + (l.get("alt") or ""), cfg, p.nome)
            if pista["lado"]:
                l["lado"], l["lado_confianca"] = pista["lado"], 0.95
        for l in ls:
            if l.get("lado"):
                continue
            larg = float(l.get("largura_rel") or 0)
            tem_costas = "costas" in p.lados_descricao
            if tem_costas and larg >= LIMITE_PEITO:
                l["lado"], l["lado_confianca"] = "costas", 0.85
            elif larg and larg < LIMITE_PEITO and len(ls) > 1:
                l["lado"], l["lado_confianca"] = "frente", 0.8
        sem = [l for l in ls if not l.get("lado")]
        if sem and any(l.get("lado") == "costas" for l in ls):
            # a outra foto da mesma cor, sem estampa grande, é a frente (lisa ou com logo pequeno)
            for l in sem:
                l["lado"], l["lado_confianca"] = "frente", 0.75
        sem = [l for l in ls if not l.get("lado")]
        if sem:
            vi = p.imagem_variante.get(cor, "")
            for l in sem:
                if vi and l.get("url") and l["url"].split("?")[0] == vi.split("?")[0]:
                    l["lado"] = "costas" if "costas" in p.lados_descricao else "frente"
                    l["lado_confianca"] = 0.7
        sem = [l for l in ls if not l.get("lado")]
        if len(sem) >= 2:
            # o decote da frente aparece mais fundo (vemos a parte de dentro da gola de trás)
            sem.sort(key=lambda l: float(l.get("gola_prof_rel") or 0))
            sem[0]["lado"], sem[0]["lado_confianca"] = "frente", 0.5
            for l in sem[1:]:
                l["lado"], l["lado_confianca"] = "costas", 0.5
        for l in ls:
            if not l.get("lado"):
                l["lado"], l["lado_confianca"] = ("costas" if "costas" in p.lados_descricao else "frente"), 0.3
            if float(l.get("lado_confianca") or 0) < 0.6 or float(l.get("cor_confianca") or 0) < 0.3:
                l["revisar"] = "sim"


def analisar(produtos: List[Produto], pasta_atuais: Path, pasta_analise: Path, cfg: dict,
             pasta_extra: Optional[Path] = None, workers: int = 1, progresso=None) -> List[dict]:
    itens = listar_imagens(produtos, pasta_atuais, pasta_extra)
    pasta_rec = pasta_analise / "recortes"
    args = [(p, arq, im, cfg, pasta_rec) for p, arq, im in itens]
    linhas: List[dict] = []
    if workers > 1 and len(args) > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for i, l in enumerate(ex.map(_uma, args, chunksize=2), 1):
                linhas.append(l)
                if progresso:
                    progresso(i, len(args), l)
    else:
        for i, a in enumerate(args, 1):
            linhas.append(_uma(a))
            if progresso:
                progresso(i, len(args), linhas[-1])
    decidir_lados(linhas, {p.handle: p for p in produtos}, cfg)
    return linhas


def salvar(linhas: List[dict], destino: Path) -> None:
    escrever_csv_dicts(destino, COLUNAS_ANALISE, linhas)
