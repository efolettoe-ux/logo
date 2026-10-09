"""Comando baixar: copia as fotos atuais da loja (Image Src + Variant Image do CSV) para atuais/{handle}/.

Só usa a biblioteca padrão (urllib). 8 downloads ao mesmo tempo, novas tentativas com espera crescente,
e pode ser interrompido: o que já baixou é pulado na próxima vez (arquivo parcial termina em .part).
O nome do arquivo é o mesmo do CDN do Shopify — é assim que o analisar liga a foto à linha do CSV.
"""
from __future__ import annotations

import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from catalogo import ErroUsuario, Produto, escrever_csv_dicts, ler_catalogo

AVISO_CERTIFICADO = (
    "O Python deste Mac não reconhece os certificados de segurança (CERTIFICATE_VERIFY_FAILED).\n"
    "Para resolver, faça UMA destas opções e rode o baixar de novo:\n"
    "  1) Abra o Finder > Aplicativos > pasta 'Python 3.x' e dê dois cliques em 'Install Certificates.command';\n"
    "  2) ou, no Terminal:  pip3 install certifi"
)

COLUNAS_LISTA = ["handle", "NOME", "arquivo", "url", "posicao", "alt", "cores_variante", "status", "observacao"]


def url_com_largura(url: str, largura: Optional[int]) -> str:
    """Pede ao CDN do Shopify a largura indicada (?width=1500). Outras URLs ficam como estão."""
    if not largura or ("cdn.shopify.com" not in url and "/cdn/shop/" not in url):
        return url
    partes = urllib.parse.urlsplit(url)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(partes.query, keep_blank_values=True) if k != "width"]
    q.append(("width", str(int(largura))))
    return urllib.parse.urlunsplit(partes._replace(query=urllib.parse.urlencode(q)))


def nome_arquivo(url: str) -> str:
    return urllib.parse.unquote(urllib.parse.urlsplit(url).path.rstrip("/").split("/")[-1]) or "imagem"


def contexto_ssl() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def eh_erro_certificado(e: BaseException) -> bool:
    txt = f"{e} {getattr(e, 'reason', '')}"
    return "CERTIFICATE_VERIFY_FAILED" in txt or isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError)


def baixar_um(url: str, destino: Path, tentativas: int = 4, timeout: float = 40, ctx=None,
              espera_base: float = 1.0) -> Tuple[str, str]:
    """Retorna (status, observacao). status: ok | pulado | erro | certificado."""
    if destino.exists() and destino.stat().st_size > 0:
        return "pulado", "já estava baixado"
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_name(destino.name + ".part")
    ultimo = ""
    for i in range(max(1, tentativas)):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (PALLACIO estampas)"})
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r, open(parcial, "wb") as f:
                while True:
                    bloco = r.read(1 << 16)
                    if not bloco:
                        break
                    f.write(bloco)
            if parcial.stat().st_size == 0:
                raise OSError("arquivo vazio")
            parcial.replace(destino)
            return "ok", ""
        except urllib.error.HTTPError as e:
            ultimo = f"HTTP {e.code}"
            if e.code in (400, 401, 403, 404, 410):
                break  # não adianta tentar de novo
        except Exception as e:  # noqa: BLE001 — rede instável: tenta de novo
            if eh_erro_certificado(e):
                try:
                    parcial.unlink()
                except OSError:
                    pass
                return "certificado", "CERTIFICATE_VERIFY_FAILED"
            ultimo = f"{type(e).__name__}: {e}"
        if i < tentativas - 1:
            time.sleep(espera_base * (2 ** i))
    try:
        parcial.unlink()
    except OSError:
        pass
    return "erro", ultimo


def itens_para_baixar(produtos: List[Produto], pasta: Path, largura: Optional[int]) -> List[dict]:
    out = []
    for p in produtos:
        cores_por_url = {}
        for cor, u in p.imagem_variante.items():
            cores_por_url.setdefault(u.split("?")[0], []).append(cor)
        vistos = set()
        for im in p.imagens:
            base = im.url.split("?")[0]
            if base in vistos:
                continue
            vistos.add(base)
            out.append({"handle": p.handle, "NOME": p.nome, "url": url_com_largura(im.url, largura),
                        "arquivo": str(pasta / p.handle / nome_arquivo(im.url)), "posicao": im.posicao,
                        "alt": im.alt, "cores_variante": " / ".join(cores_por_url.get(base, []))})
    return out


def baixar_tudo(itens: List[dict], workers: int = 8, tentativas: int = 4, timeout: float = 40,
                progresso: Optional[Callable] = None, ctx=None, espera_base: float = 1.0) -> List[dict]:
    ctx = ctx if ctx is not None else contexto_ssl()

    def um(it):
        st, obs = baixar_um(it["url"], Path(it["arquivo"]), tentativas, timeout, ctx, espera_base)
        return dict(it, status=st, observacao=obs)

    res = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        for i, r in enumerate(ex.map(um, itens), 1):
            res.append(r)
            if progresso:
                progresso(i, len(itens), r)
    return res


def comando(proj, args) -> None:
    cfg = proj.cfg
    bcfg = cfg.get("baixar", {})
    produtos = ler_catalogo(proj.caminho_csv(getattr(args, "csv", None)), cfg, proj.tipo)
    filtro = set()
    for v in getattr(args, "produto", None) or []:
        filtro |= {x.strip().upper() for x in v.split(",") if x.strip()}
    if filtro:
        produtos = [p for p in produtos if p.nome in filtro or p.handle.upper() in filtro]
        if not produtos:
            raise ErroUsuario("Nenhum produto com esse nome. Use o NOME do diagnóstico (ex.: MARTINI).")
    pasta = proj.pasta("atuais", criar=True)
    largura = getattr(args, "largura", None) or bcfg.get("largura", 1500)
    itens = itens_para_baixar(produtos, pasta, largura)
    print(f"{len(produtos)} produtos, {len(itens)} fotos. Baixando para {pasta} ...")
    from pallacio import _barra
    res = baixar_tudo(itens, int(getattr(args, "workers", None) or bcfg.get("workers", 8)),
                      int(bcfg.get("tentativas", 4)), float(bcfg.get("timeout", 40)),
                      progresso=lambda i, n, r: _barra(i, n, r["NOME"]))
    escrever_csv_dicts(pasta / "lista.csv", COLUNAS_LISTA, res)
    from collections import Counter
    c = Counter(r["status"] for r in res)
    print(f"Baixadas: {c.get('ok', 0)} | já existiam: {c.get('pulado', 0)} | com erro: {c.get('erro', 0) + c.get('certificado', 0)}")
    if c.get("certificado"):
        raise ErroUsuario(AVISO_CERTIFICADO)
    if c.get("erro"):
        print(f"Veja quais falharam em {pasta / 'lista.csv'} (coluna status). Rode o baixar de novo para tentar só essas.")
    print("Próximo passo: python3 pallacio.py analisar")
