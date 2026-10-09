"""Catálogo PALLACIO: configuração, leitura do CSV do Shopify, cores, nomes e formatos de arquivo.

Tudo que é "regra de negócio" (cores, códigos, nomes de arquivo, ordem frente/costas) mora aqui.
"""
from __future__ import annotations

import copy
import csv
import html
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


class ErroUsuario(Exception):
    """Erro esperado (arquivo faltando, config errada...). O CLI mostra só a mensagem, sem traceback."""


# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

CONFIG_PADRAO: dict = {
    "versao": 1,
    "csv": "products_export_1.csv",
    "pastas": {
        "atuais": "atuais",
        "analise": "analise",
        "estampas": "estampas",
        "estampas_normalizadas": "estampas_normalizadas",
        "saida": "saida",
        "saida_web": "saida_web",
        "saida_previa": "saida_previa",
    },
    "arquivos": {
        "diagnostico_html": "diagnostico.html",
        "diagnostico_csv": "diagnostico.csv",
        "analise_csv": "analise.csv",
        "mapa_csv": "mapa.csv",
        "revisao_html": "revisao.html",
        "relatorio_csv": "relatorio.csv",
        "antes_depois_html": "antes_depois.html",
        "folha_contato": "folha_contato.jpg",
        "areas_json": "areas.json",
    },
    "tipos": {
        "camiseta": {
            "tipo_csv": ["T-Shirt"],
            "sufixos_titulo": [" T-SHIRT", " TSHIRT", " T SHIRT", " TEE"],
            # Primeira pasta que existir (relativa à pasta do projeto). Também dá para usar --mockups.
            "pasta_mockups": ["mockups", "CAMISETAS 5 CORES", "CAMISETAS 5 CORES - cópia",
                              "MOCKUPS FINAIS/CAMISETAS 5 CORES"],
        },
        "moletom": {
            "tipo_csv": ["Hoodie"],
            "sufixos_titulo": [" HOODIE", " MOLETOM"],
            "pasta_mockups": ["mockups-moletom", "MOCKUPS FINAIS/MOLETONS"],
        },
    },
    "produtos": {
        "incluir_nao_ativos": False,
        "excluir_handles": [],
        "palavras_teste": ["teste"],
    },
    # Tabela de cores: adicione a 5a cor aqui (nome, código, apelidos, tom e RGB de referência).
    "cores": [
        # rgb_referencia = cor do tecido medida nas fotos atuais da loja (JA FOI, mediana de 24 fotos por cor)
        {"nome": "Branca", "codigo": "BR", "tom": "claro", "rgb_referencia": [241, 241, 243],
         "apelidos": ["branca", "branco", "white", "br", "wht"]},
        {"nome": "Off White", "codigo": "OW", "tom": "claro", "rgb_referencia": [241, 235, 224],
         "apelidos": ["off white", "offwhite", "off-white", "off", "ow", "creme", "cream", "perola"]},
        {"nome": "Preta", "codigo": "PT", "tom": "escuro", "rgb_referencia": [23, 23, 22],
         "apelidos": ["preta", "preto", "black", "pt", "blk"]},
        {"nome": "Azul Marinho", "codigo": "AZ", "tom": "escuro", "rgb_referencia": [40, 47, 67],
         "apelidos": ["azul marinho", "marinho", "navy", "azul", "az"]},
        # 5a cor: já tem mockup ("chumbo-*.png"). Para ativar, troque "ativa" para true.
        {"nome": "Chumbo", "codigo": "CH", "tom": "escuro", "rgb_referencia": [49, 48, 50], "ativa": False,
         "apelidos": ["chumbo", "grafite", "cinza chumbo", "ch"]},
        # Cores especiais (bicolor): precisam de mockups próprios; sem eles o status é sem_mockup.
        {"nome": "Branca / Azul Claro", "codigo": "BR-AZC", "tom": "claro", "rgb_referencia": [240, 240, 238],
         "apelidos": ["branca azul claro"], "especial": True},
        {"nome": "Branca / Azul Escuro", "codigo": "BR-AZE", "tom": "claro", "rgb_referencia": [240, 240, 238],
         "apelidos": ["branca azul escuro"], "especial": True},
        {"nome": "Branca / Azul", "codigo": "BR-AZL", "tom": "claro", "rgb_referencia": [240, 240, 238],
         "apelidos": ["branca azul"], "especial": True},
        {"nome": "Branca / Preta", "codigo": "BR-PT", "tom": "claro", "rgb_referencia": [240, 240, 238],
         "apelidos": ["branca preta"], "especial": True},
        {"nome": "Preta / Vermelha", "codigo": "PT-VM", "tom": "escuro", "rgb_referencia": [30, 30, 32],
         "apelidos": ["preta vermelha"], "especial": True},
    ],
    "palavras_lado": {
        "frente": ["frente", "front", "frontal", "peito", "frt"],
        "costas": ["costas", "back", "verso", "tras", "traseira", "costa"],
    },
    # Mockups lisos: o nome do arquivo diz cor e vista (ex.: "preta-costas.png", "off-white-close-costas.png").
    "mockups": {
        "palavras_vista": {
            "costas-inclinada": ["costas inclinada", "inclinada", "inclinado", "diagonal"],
            "close-costas": ["close costas", "close", "detalhe", "zoom"],
            "frente": ["frente", "front", "frontal"],
            "costas": ["costas", "back", "verso"],
        },
        # Nome do arquivo -> {"cor": "Preta", "vista": "frente|costas|close-costas"}; vence a detecção pelo nome.
        "explicitos": {},
        # Tronco marcado à mão no calibrador (frações da imagem), por nome de arquivo do mockup.
        "torso_manual": {},
    },
    "nomes": {
        "prefixo": "PALL",
        # Frente sem estampa (produto só com costas): "exportar" gera a frente lisa como 02; "pular" não gera.
        "frente_lisa": "exportar",
        "costas_lisa": "pular",
    },
    # Onde a estampa vai quando o produto ainda não tem medida (origem=padrao). Medido nas 12 camisetas
    # JA FOI (96 fotos, tronco medido na borda nítida do tecido, sem a sombra): costas = mediana de 48
    # fotos; frente = logo pequeno no peito esquerdo (36 fotos).
    # largura_rel = largura da estampa / largura do tronco; topo_rel = (topo da estampa - gola) / altura do
    # tronco; centro_x_rel = (centro da estampa - centro do tronco) / largura do tronco (+ = direita da foto).
    "geometria_padrao": {
        "costas": {"largura_rel": 0.67, "topo_rel": 0.190, "centro_x_rel": 0.0,
                   # arte larga (altura/largura <= 0,9) vai até 0,75 do tronco; arte alta é limitada pela
                   # altura (no máximo 0,545 da altura do tronco). Tronco da loja: largura/altura = 0,562.
                   "largura_rel_larga": 0.75, "aspecto_largo": 0.9, "aspecto_alto": 1.3,
                   "altura_rel_max": 0.545, "razao_torso": 0.562},
        "frente": {"largura_rel": 0.238, "topo_rel": 0.257, "centro_x_rel": 0.273},
        "frente_grande": {"largura_rel": 0.63, "topo_rel": 0.20, "centro_x_rel": 0.0},
    },
    # Ajuste para TODAS as estampas (ex.: escala 1.05 = 5% maiores; deslocar_topo_rel 0.01 = um pouco abaixo).
    "ajuste_global": {"escala": 1.0, "deslocar_topo_rel": 0.0},
    # Tamanho da arte no mockup novo. O tronco do mockup novo é mais estreito para a altura dele
    # (largura/altura 0,513) que o das fotos da loja (0,562): medir só pela largura deixaria a arte ~10%
    # menor na peça. A largura é multiplicada por (razão da loja / razão do mockup) ** peso_altura
    # (0 = só largura, 1 = só altura, 0,5 = meio-termo). razao_tronco_loja é usada quando não há analise.csv.
    "tamanho": {"razao_tronco_loja": 0.562, "peso_altura": 0.5},
    # estampar: o que fazer com linhas pendentes do mapa.csv.
    "estampar": {
        # true = só gera a cor quando frente E costas têm arte; false = gera os lados que têm arte e
        # lista o lado que falta como sem_estampa no relatorio.csv.
        "so_cores_completas": False,
        # Confere a arte sem fundo antes de estampar: restos de fundo (nuvens cinza, faixas de degradê
        # nas bordas) bloqueiam a imagem com status "revisar".
        "verificar_residuo": True,
        # Fotos extras das costas: a inclinada (mockup "*-costas-inclinada.png") entra como 03 sempre que
        # existir; o close ("*-close-costas.png") só entra se usar_close for true (vira 04).
        "usar_close": False,
        # Tamanho da estampa das costas (fotos 01 e 03) em relação à loja: 0.85 = 15% menor.
        "escala_costas": 0.85,
        # Ajustes só da foto inclinada: tamanho extra (1.0 = igual à 01) e quanto subir a estampa
        # (fração da altura do tronco).
        "escala_inclinada": 1.0,
        "subir_inclinada": 0.03,
    },
    # Estampa da frente com largura_rel acima disso é "grande" (centralizada), abaixo é logo de peito.
    "limite_frente_grande": 0.40,
    # Imagem final igual às fotos da loja: quadrado, fundo cinza-claro, peça ocupando a mesma fração.
    # Medido nas fotos JA FOI (1254x1254): fundo RGB(237,237,237) (230-244 com a vinheta); peça com
    # 57,2% da largura e 59,0% da altura do quadro, centro em (50,1%, 51,2%).
    "enquadramento": {
        "formato": "quadrado",          # quadrado | original
        "lado": 2048,
        "fundo": "cor",                 # cor | transparente
        "cor_fundo": [237, 237, 237],
        "ocupacao_largura": 0.572,
        "ocupacao_altura": 0.590,
        "centro": [0.501, 0.512],
        "sombra_opacidade": 0.0,        # sombra suave sob a peça (0 = sem; experimente 0.12)
        "close": "inteiro",             # close-costas: inteiro (detalhe todo, com fundo nas laterais) | preencher
        "salvar_png_transparente": True,
    },
    "analise": {
        "lado_max_segmentacao": 600,
        "lado_max_estampa": 1200,
        "tolerancia_fundo": 14.0,
        "limiar_estampa_min": 13.0,
        "peso_luminancia": 0.55,
        "area_min_componente": 0.00025,
        "limiar_borda_min": 0.12,
        "margem_costura_rel": 0.045,
    },
    "realismo": {
        # cobertura da tinta: <1 deixa a malha aparecer um pouco nos meios-tons; onde a tinta é bem mais
        # clara que o tecido (tinta branca na camisa preta) a cobertura sobe até 1 (branco fica branco).
        "opacidade_tinta": 0.95,
        "forca_sombra": 0.9,
        "forca_luz": 0.35,
        "brilho_tecido": 0.25,
        "forca_textura": 0.55,
        "deslocamento_max_rel": 0.006,
        "deslocamento_max_px": 7.0,
        "forca_deslocamento": 1.0,
        "suavizar_borda_px": 0.5,
        "granulado_tinta": 0.018,
        "sigma_dobras_rel": 0.006,
    },
    "saida": {
        "png_compressao": 6,
        "web_lado_max": 2048,
        "web_qualidade": 88,
        "previa_lado_max": 900,
        "previa_lado": 700,
        "contato_miniatura": 200,
        "contato_por_folha": 240,
    },
    "baixar": {"largura": 1500, "workers": 8, "tentativas": 4, "timeout": 40},
    # casar: onde ficam as artes e como escolher entre versões repetidas.
    "casar": {
        # Pasta que contém "CAMISETAS 100%", "NOVAS", "ESTAMPAS PRONTAS P: IZZY", "MATERIAL QUALITY 100%".
        # Vazio = procura sozinho (a pasta do projeto e a pasta acima dela). Também dá para usar --arquivos.
        "pasta_arquivos": "",
        "pastas_estampas": ["CAMISETAS 100%", "NOVAS", "ESTAMPAS PRONTAS P: IZZY", "MATERIAL QUALITY 100%", "estampas"],
        # Quando há a mesma arte em várias pastas, vence a primeira desta lista (depois: PNG transparente,
        # texto sem erro, maior resolução).
        "prioridade_fontes": ["ESTAMPAS PRONTAS P: IZZY", "MATERIAL QUALITY 100%", "CAMISETAS 100%", "estampas", "NOVAS"],
        # Fotos atuais no formato "JA FOI" (uma subpasta por produto) usadas pelo analisar sem --fotos.
        "pasta_fotos_extra": "CAMISETAS 100%/JA FOI",
        "confianca_minima": 0.6,       # abaixo disso a linha vai para revisão
        "contraste_minimo": 25.0,      # diferença de luminosidade (L*) tinta x tecido para ser legível
        "hash_visual_distancia": 6,    # duplicata visual: até 6 bits diferentes em 64
    },
}


def _mesclar(base: dict, extra: dict) -> dict:
    """Mescla config do usuário sobre o padrão (chaves novas do padrão continuam existindo)."""
    out = copy.deepcopy(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _mesclar(out[k], v)
        else:
            out[k] = v
    return out


def carregar_config(caminho: Path) -> dict:
    """Lê config.json; cria com os padrões se não existir."""
    caminho = Path(caminho)
    if not caminho.exists():
        caminho.write_text(json.dumps(CONFIG_PADRAO, ensure_ascii=False, indent=2), encoding="utf-8")
        return copy.deepcopy(CONFIG_PADRAO)
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ErroUsuario(
            f"O arquivo {caminho.name} tem um erro de digitação na linha {e.lineno}, coluna {e.colno}.\n"
            f"Confira vírgulas e aspas. Dica: apague o arquivo para ele ser recriado com os valores padrão."
        )
    return _mesclar(CONFIG_PADRAO, dados)


@dataclass
class Projeto:
    """Pasta de trabalho + config. Todos os comandos recebem um Projeto."""
    raiz: Path
    cfg: dict
    tipo: str = "camiseta"

    def pasta(self, chave: str, criar: bool = False) -> Path:
        p = self.raiz / self.cfg["pastas"][chave]
        if criar:
            p.mkdir(parents=True, exist_ok=True)
        return p

    def arquivo(self, chave: str) -> Path:
        return self.raiz / self.cfg["arquivos"][chave]

    @property
    def tipo_cfg(self) -> dict:
        tipos = self.cfg["tipos"]
        if self.tipo not in tipos:
            raise ErroUsuario(f"Tipo de peça '{self.tipo}' não existe no config.json. Opções: {', '.join(tipos)}.")
        return tipos[self.tipo]

    def caminho_csv(self, informado: Optional[str] = None) -> Path:
        """Acha o CSV do Shopify: --csv, config, ou o primeiro products_export*.csv da pasta."""
        if informado:
            p = Path(informado).expanduser()
            p = p if p.is_absolute() else (self.raiz / p)
            if not p.exists():
                raise ErroUsuario(f"Não achei o CSV informado: {p}")
            return p
        p = self.raiz / self.cfg.get("csv", "")
        if self.cfg.get("csv") and p.exists():
            return p
        candidatos = sorted(self.raiz.glob("products_export*.csv")) + sorted(self.raiz.glob("*.csv"))
        candidatos = [c for c in candidatos if c.name not in {
            Path(v).name for v in self.cfg["arquivos"].values()}]
        if candidatos:
            return candidatos[0]
        raise ErroUsuario(
            "Não achei o CSV de produtos do Shopify.\n"
            "Exporte em Shopify > Produtos > Exportar (CSV para Excel/Numbers) e coloque o arquivo "
            f"nesta pasta com o nome {self.cfg.get('csv')}, ou use --csv CAMINHO."
        )


# ---------------------------------------------------------------------------
# Texto e cores
# ---------------------------------------------------------------------------

def sem_acentos(txt: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", txt) if not unicodedata.combining(c))


def tokens(txt: str) -> List[str]:
    """'PALL-TRACK-PT_01-costas.png' -> ['pall','track','pt','01','costas','png']."""
    t = sem_acentos(txt).lower()
    t = re.sub(r"([a-z])([0-9])|([0-9])([a-z])", lambda m: " ".join(g for g in m.groups() if g), t)
    return [x for x in re.split(r"[^a-z0-9]+", t) if x]


def chave_cor(txt: str) -> str:
    """Forma comparável de uma cor: sem acento, minúscula, só letras/números separados por espaço."""
    return " ".join(re.split(r"[^a-z0-9]+", sem_acentos(txt).lower())).strip()


@dataclass
class Cor:
    nome: str
    codigo: str
    tom: str
    rgb: Tuple[int, int, int]
    apelidos: List[str]
    especial: bool = False
    ativa: bool = True


def tabela_cores(cfg: dict) -> List[Cor]:
    out = []
    for c in cfg["cores"]:
        out.append(Cor(c["nome"], c["codigo"], c.get("tom", "claro"), tuple(c.get("rgb_referencia", [128, 128, 128])),
                       [chave_cor(a) for a in c.get("apelidos", [])], bool(c.get("especial", False)),
                       bool(c.get("ativa", True))))
    return out


def cor_por_nome(nome: str, cfg: dict) -> Optional[Cor]:
    for c in tabela_cores(cfg):
        if c.nome == nome:
            return c
    return None


def normalizar_cor(valor: str, cfg: dict) -> Tuple[str, bool]:
    """Valor do CSV -> (nome canônico, conhecido?). 'Azul marinho' -> ('Azul Marinho', True)."""
    k = chave_cor(valor)
    if not k:
        return "", False
    cores = tabela_cores(cfg)
    for c in cores:
        if chave_cor(c.nome) == k or chave_cor(c.codigo) == k:
            return c.nome, True
    for c in cores:
        if k in c.apelidos:
            return c.nome, True
    # desconhecida: mantém o texto com espaços arrumados
    return re.sub(r"\s*/\s*", " / ", valor.strip()), False


def _achar_sequencia(tks: List[str], seq: List[str]) -> int:
    n = len(seq)
    for i in range(len(tks) - n + 1):
        if tks[i:i + n] == seq:
            return i
    return -1


def _colapsar(t: str) -> str:
    """'frrente' -> 'frente', 'offwhite' -> 'ofwhite' (tolerância a letra repetida)."""
    return re.sub(r"(.)\1+", r"\1", t)


def pistas_texto(texto: str, cfg: dict, nome_produto: str = "") -> dict:
    """Procura cor e lado em nome de arquivo / alt text.

    Retorna {"cor": nome|None, "lado": "frente"|"costas"|None, "liso": bool, "numero": int|None}.
    Remove antes os tokens do nome do produto (ex.: PERIGNON-VERDE não vira cor).
    Aceita palavras grudadas ('FRENTEBRANCA') e letra repetida ('frrente').
    """
    tks = tokens(texto)
    if nome_produto:
        seq = tokens(nome_produto)
        i = _achar_sequencia(tks, seq) if seq else -1
        if i >= 0:
            tks = tks[:i] + ["_"] + tks[i + len(seq):]
    tks = [_colapsar(t) for t in tks if t not in {"pall", "png", "jpg", "jpeg", "webp", "copia", "copy", "t", "shirt", "tshirt", "cam"}]
    res = {"cor": None, "lado": None, "liso": False, "numero": None}
    # cor: apelidos mais longos primeiro ("off white" antes de "white")
    pares = []
    for c in tabela_cores(cfg):
        for a in [chave_cor(c.nome), chave_cor(c.codigo)] + c.apelidos:
            if a:
                pares.append(([_colapsar(x) for x in a.split()], c.nome))
    pares.sort(key=lambda p: -len(" ".join(p[0])))
    resto = list(tks)
    for seq, nome in pares:
        i = _achar_sequencia(resto, seq)
        if i >= 0:
            res["cor"] = nome
            resto = resto[:i] + ["_"] + resto[i + len(seq):]
            break
    lados = [(lado, [_colapsar(chave_cor(p)) for p in ps]) for lado, ps in cfg["palavras_lado"].items()]
    for lado, palavras in lados:
        if any(p in resto for p in palavras):
            res["lado"] = lado
            break
    # palavras grudadas: procura dentro dos tokens (só apelidos com 5+ letras, para não achar por acaso)
    if res["cor"] is None or res["lado"] is None:
        for t in resto:
            if res["lado"] is None:
                for lado, palavras in lados:
                    if any(len(p) >= 5 and p in t for p in palavras):
                        res["lado"] = lado
                        break
            if res["cor"] is None:
                for seq, nome in pares:
                    a = "".join(seq)
                    if len(a) >= 5 and a in t:
                        res["cor"] = nome
                        break
    res["liso"] = any(t in resto for t in ("padrao", "lisa", "liso", "plain", "blank"))
    for t in resto:
        if re.fullmatch(r"0[0-9]", t):
            res["numero"] = int(t)
            break
    return res


# ---------------------------------------------------------------------------
# Nomes de saída
# ---------------------------------------------------------------------------

def nome_produto(titulo: str, sufixos: Iterable[str]) -> str:
    """'ÁLCOOL T-SHIRT' -> 'ALCOOL'; 'MONEY TALKS T-SHIRT' -> 'MONEY-TALKS'; 'DRIVER’S' -> 'DRIVERS'."""
    t = titulo.strip()
    for suf in sorted(sufixos, key=len, reverse=True):
        if t.upper().endswith(suf.upper()):
            t = t[: -len(suf)]
            break
    t = sem_acentos(t).upper()
    t = re.sub(r"[’'`´]", "", t)
    t = re.sub(r"[^A-Z0-9]+", "-", t).strip("-")
    return t or "SEM-NOME"


def numeracao_lados(tem_costas: bool, tem_frente: bool, cfg: dict) -> Dict[str, int]:
    """Regra da marca: com estampa nas costas -> costas 01, frente 02. Só frente -> frente 01.

    tem_costas/tem_frente = o lado TEM estampa. A frente lisa entra como 02 se nomes.frente_lisa == 'exportar'.
    """
    out: Dict[str, int] = {}
    if tem_costas:
        out["costas"] = 1
        if tem_frente or cfg["nomes"].get("frente_lisa", "exportar") == "exportar":
            out["frente"] = 2
    elif tem_frente:
        out["frente"] = 1
        if cfg["nomes"].get("costas_lisa", "pular") == "exportar":
            out["costas"] = 2
    return out


def nome_arquivo_saida(nome: str, codigo: str, numero: int, lado: str, ext: str, cfg: dict) -> str:
    return f"{cfg['nomes'].get('prefixo', 'PALL')}-{nome}-{codigo}_{numero:02d}-{lado}.{ext.lstrip('.')}"


# ---------------------------------------------------------------------------
# CSV do Shopify
# ---------------------------------------------------------------------------

@dataclass
class ImagemLoja:
    url: str
    posicao: int
    alt: str = ""

    @property
    def nome_arquivo(self) -> str:
        return self.url.split("?")[0].rstrip("/").split("/")[-1]


@dataclass
class Produto:
    handle: str
    titulo: str
    nome: str
    tipo_csv: str
    status: str
    corpo: str
    cores: List[str] = field(default_factory=list)            # nomes canônicos, na ordem do CSV
    cores_originais: Dict[str, str] = field(default_factory=dict)  # canônico -> como está no CSV
    cores_desconhecidas: List[str] = field(default_factory=list)
    imagens: List[ImagemLoja] = field(default_factory=list)   # ordenadas pela posição
    imagem_variante: Dict[str, str] = field(default_factory=dict)  # cor canônica -> URL da imagem principal
    lados_descricao: List[str] = field(default_factory=list)  # ["costas"], ["frente","costas"], ["frente"], []
    eh_teste: bool = False


def texto_descricao(corpo_html: str) -> str:
    t = re.sub(r"<[^>]+>", " ", corpo_html or "")
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def lados_da_descricao(corpo_html: str) -> List[str]:
    """Onde a descrição diz que há estampa. 'estampa frontal' e 'na frente' contam como frente."""
    t = sem_acentos(texto_descricao(corpo_html)).lower()
    frente = bool(re.search(r"\bfrente\b|\bfrontal\b|\bpeito\b", t))
    costas = bool(re.search(r"\bcostas\b", t))
    return [l for l, ok in (("frente", frente), ("costas", costas)) if ok]


def ler_linhas_csv(caminho: Path) -> List[dict]:
    for enc in ("utf-8-sig", "latin-1"):
        try:
            with open(caminho, newline="", encoding=enc) as f:
                linhas = list(csv.DictReader(f))
            break
        except UnicodeDecodeError:
            continue
    if not linhas or "Handle" not in linhas[0]:
        raise ErroUsuario(f"O arquivo {Path(caminho).name} não parece um export de produtos do Shopify (falta a coluna Handle).")
    return linhas


def ler_catalogo(caminho: Path, cfg: dict, tipo: Optional[str] = None, incluir_excluidos: bool = False) -> List[Produto]:
    """Lê o CSV e agrupa por Handle. tipo='camiseta'|'moletom' filtra pela coluna Type.

    Produtos de teste / não ativos ficam de fora, a não ser que incluir_excluidos=True (o diagnóstico usa).
    """
    linhas = ler_linhas_csv(caminho)
    grupos: Dict[str, List[dict]] = {}
    for ln in linhas:
        h = (ln.get("Handle") or "").strip()
        if h:
            grupos.setdefault(h, []).append(ln)
    tipos_csv = None
    sufixos: List[str] = []
    if tipo:
        tcfg = cfg["tipos"][tipo]
        tipos_csv = {t.lower() for t in tcfg["tipo_csv"]}
        sufixos = tcfg.get("sufixos_titulo", [])
    else:
        for t in cfg["tipos"].values():
            sufixos += t.get("sufixos_titulo", [])
    pcfg = cfg.get("produtos", {})
    produtos = []
    for h, lns in grupos.items():
        principal = next((l for l in lns if (l.get("Title") or "").strip()), lns[0])
        tipo_csv = (principal.get("Type") or "").strip()
        if tipos_csv is not None and tipo_csv.lower() not in tipos_csv:
            continue
        titulo = (principal.get("Title") or "").strip()
        status = (principal.get("Status") or "").strip().lower()
        p = Produto(h, titulo, nome_produto(titulo, sufixos), tipo_csv, status, principal.get("Body (HTML)") or "")
        palavras = [w.lower() for w in pcfg.get("palavras_teste", [])]
        p.eh_teste = any(w in tokens(titulo) for w in palavras) or h in pcfg.get("excluir_handles", [])
        imgs: Dict[str, ImagemLoja] = {}
        for ln in lns:
            v = (ln.get("Option1 Value") or "").strip()
            if v:
                nome, ok = normalizar_cor(v, cfg)
                if nome not in p.cores:
                    p.cores.append(nome)
                    p.cores_originais[nome] = v
                    if not ok:
                        p.cores_desconhecidas.append(nome)
                vi = (ln.get("Variant Image") or "").strip()
                if vi and nome not in p.imagem_variante:
                    p.imagem_variante[nome] = vi
            src = (ln.get("Image Src") or "").strip()
            if src and src not in imgs:
                try:
                    pos = int(ln.get("Image Position") or 0)
                except ValueError:
                    pos = 0
                imgs[src] = ImagemLoja(src, pos, (ln.get("Image Alt Text") or "").strip())
        # Variant Image que não está nas imagens também conta (pode estar só no variante)
        for vi in p.imagem_variante.values():
            if vi not in imgs:
                imgs[vi] = ImagemLoja(vi, 999, "")
        p.imagens = sorted(imgs.values(), key=lambda i: (i.posicao, i.url))
        p.lados_descricao = lados_da_descricao(p.corpo)
        excluido = p.eh_teste or (status != "active" and not pcfg.get("incluir_nao_ativos", False))
        if excluido and not incluir_excluidos:
            continue
        produtos.append(p)
    return produtos


def produto_excluido(p: Produto, cfg: dict) -> bool:
    return p.eh_teste or (p.status != "active" and not cfg.get("produtos", {}).get("incluir_nao_ativos", False))


# ---------------------------------------------------------------------------
# mapa.csv e analise.csv (formatos compartilhados entre comandos)
# ---------------------------------------------------------------------------

COLUNAS_MAPA = ["handle", "NOME", "cor", "lado", "arquivo_estampa", "id_normalizado", "confianca",
                "largura_rel", "topo_rel", "centro_x_rel", "origem", "revisar", "observacao", "ajuste_tinta"]

# Valor especial em id_normalizado (ou arquivo_estampa) para "este lado é liso de propósito".
LISO = "liso"

COLUNAS_ANALISE = ["handle", "NOME", "arquivo", "url", "posicao", "alt", "cor", "cor_confianca", "cor_medida",
                   "rgb_tecido", "lado", "lado_confianca", "gola_prof_rel", "tem_estampa",
                   "bbox_x0", "bbox_y0", "bbox_x1", "bbox_y1", "largura_rel", "topo_rel", "centro_x_rel",
                   "aspecto", "torso_x0", "torso_x1", "torso_topo", "torso_base", "largura_img", "altura_img",
                   "recorte", "revisar", "observacao"]


@dataclass
class LinhaMapa:
    handle: str
    NOME: str = ""
    cor: str = ""
    lado: str = ""
    arquivo_estampa: str = ""
    id_normalizado: str = ""
    confianca: str = ""
    largura_rel: str = ""
    topo_rel: str = ""
    centro_x_rel: str = ""
    origem: str = ""
    revisar: str = ""
    observacao: str = ""
    ajuste_tinta: str = ""     # ex.: "L=+12;a=-2;b=-18" (desloca a cor da tinta, em Lab)

    @property
    def eh_liso(self) -> bool:
        return self.id_normalizado.strip().lower() == LISO or self.arquivo_estampa.strip().upper() == "LISO"

    @property
    def tem_estampa(self) -> bool:
        return not self.eh_liso and bool(self.id_normalizado.strip() or self.arquivo_estampa.strip())

    def geometria(self) -> Optional[Tuple[float, float, float]]:
        """(largura_rel, topo_rel, centro_x_rel) ou None se faltar número."""
        try:
            return (_num(self.largura_rel), _num(self.topo_rel), _num(self.centro_x_rel or "0"))
        except ValueError:
            return None


def _num(s: str) -> float:
    return float(str(s).strip().replace(",", "."))


def ler_mapa(caminho: Path, cfg: Optional[dict] = None) -> List[LinhaMapa]:
    """Lê mapa.csv (aceita ; ou , como separador, como o Excel/Numbers salvam)."""
    caminho = Path(caminho)
    if not caminho.exists():
        return []
    texto = caminho.read_text(encoding="utf-8-sig")
    primeira = texto.splitlines()[0] if texto else ""
    sep = ";" if primeira.count(";") > primeira.count(",") else ","
    out = []
    for i, ln in enumerate(csv.DictReader(texto.splitlines(), delimiter=sep), start=2):
        ln = {(k or "").strip(): (v or "").strip() for k, v in ln.items()}
        if not ln.get("handle"):
            continue
        d = {k: ln.get(k, "") for k in COLUNAS_MAPA}
        if cfg is not None and d["cor"]:
            d["cor"] = normalizar_cor(d["cor"], cfg)[0]
        d["lado"] = d["lado"].lower()
        if d["lado"] and d["lado"] not in ("frente", "costas"):
            raise ErroUsuario(f"mapa.csv linha {i}: lado '{d['lado']}' inválido. Use frente ou costas.")
        out.append(LinhaMapa(**d))
    return out


def escrever_mapa(caminho: Path, linhas: List[LinhaMapa]) -> None:
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS_MAPA)
        w.writeheader()
        for l in linhas:
            w.writerow({k: getattr(l, k) for k in COLUNAS_MAPA})


def ler_csv_dicts(caminho: Path) -> List[dict]:
    caminho = Path(caminho)
    if not caminho.exists():
        return []
    with open(caminho, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def escrever_csv_dicts(caminho: Path, colunas: List[str], linhas: List[dict]) -> None:
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=colunas, extrasaction="ignore")
        w.writeheader()
        for l in linhas:
            w.writerow({k: l.get(k, "") for k in colunas})


# ---------------------------------------------------------------------------
# Diagnóstico (só lê o CSV)
# ---------------------------------------------------------------------------

_RE_COMPLETO = re.compile(r"^PALL-[A-Z0-9-]+-(PT|BR|OW|AZ)_\d{2}-(frente|costas)(-[a-z-]+)?\.(png|jpe?g|webp)$")


def estado_nome_imagem(nome_arquivo: str, cfg: dict) -> str:
    """completo (padrão da loja) | parcial (tem cor ou lado no nome) | aleatorio."""
    if _RE_COMPLETO.match(nome_arquivo):
        return "completo"
    p = pistas_texto(nome_arquivo, cfg)
    if p["cor"] or p["lado"]:
        return "parcial"
    return "aleatorio"


@dataclass
class LinhaDiagnostico:
    handle: str
    nome: str
    titulo: str
    status: str
    cores: List[str]
    lados_descricao: List[str]
    n_imagens: int
    imagens_por_cor: str
    estado_nomes: str
    problemas: List[str]
    gravidade: str  # ok | aviso | erro


def diagnosticar(produtos: List[Produto], cfg: dict, cores_com_mockup: Optional[set] = None) -> List[LinhaDiagnostico]:
    """Gera uma linha por produto com os problemas encontrados no CSV.

    cores_com_mockup: nomes de cor que têm mockup (frente e costas). None = pasta de mockups ainda não existe.
    """
    url_produtos: Dict[str, set] = {}
    for p in produtos:
        for im in p.imagens:
            url_produtos.setdefault(im.url.split("?")[0], set()).add(p.handle)
    nomes: Dict[str, List[str]] = {}
    for p in produtos:
        if not produto_excluido(p, cfg):
            nomes.setdefault(p.nome, []).append(p.handle)
    out = []
    for p in produtos:
        probs: List[str] = []
        grav = "ok"
        if p.eh_teste or p.status != "active":
            probs.append(f"produto de teste / não ativo ({p.status}) — fica de fora")
            grav = "aviso"
        minus = [orig for orig in p.cores_originais.values() if orig.strip() == "Azul marinho"]
        if minus:
            probs.append("cor escrita 'Azul marinho' (m minúsculo) — padronizar para 'Azul Marinho' no Shopify")
            grav = "aviso" if grav == "ok" else grav
        especiais = []
        for c in p.cores:
            info = cor_por_nome(c, cfg)
            if info is None:
                especiais.append(c)
            elif info.especial and (cores_com_mockup is None or c not in cores_com_mockup):
                especiais.append(c)
        if especiais:
            probs.append("cor especial sem mockup próprio: " + ", ".join(especiais))
            grav = "aviso" if grav == "ok" else grav
        if cores_com_mockup is not None:
            falta = [c for c in p.cores if c not in cores_com_mockup and c not in especiais]
            if falta:
                probs.append("sem mockup para: " + ", ".join(falta))
                grav = "erro"
        compart = sorted({h for im in p.imagens for h in url_produtos[im.url.split('?')[0]] if h != p.handle})
        if compart:
            probs.append("imagens iguais às do produto: " + ", ".join(compart))
            grav = "aviso" if grav == "ok" else grav
        if len(nomes.get(p.nome, [])) > 1:
            probs.append(f"NOME '{p.nome}' repetido em: " + ", ".join(nomes[p.nome]))
            grav = "erro"
        n = len(p.imagens)
        nc = max(1, len(p.cores))
        if not p.lados_descricao:
            probs.append("descrição não diz onde fica a estampa (frente/costas)")
            grav = "aviso" if grav == "ok" else grav
        # loja mostra 2 fotos por cor (costas + frente, mesmo lisa); só-frente mostra 1
        esperado = 1 if p.lados_descricao == ["frente"] else 2
        if n != esperado * nc:
            probs.append(f"{n} imagens para {nc} cores (esperado {esperado * nc} pela descrição)")
            grav = "aviso" if grav == "ok" else grav
        sem_var = [c for c in p.cores if c not in p.imagem_variante]
        if sem_var:
            probs.append("cor sem imagem de variante: " + ", ".join(sem_var))
            grav = "aviso" if grav == "ok" else grav
        if "frente" in p.lados_descricao:
            lisas = [im.nome_arquivo for im in p.imagens if pistas_texto(im.nome_arquivo, cfg, p.nome)["liso"]]
            if lisas:
                probs.append("descrição diz estampa na frente, mas há imagem 'frente-padrao' (lisa?)")
                grav = "aviso" if grav == "ok" else grav
        estados = {estado_nome_imagem(im.nome_arquivo, cfg) for im in p.imagens}
        if estados == {"completo"}:
            estado = "completo"
        elif estados == {"aleatorio"}:
            estado = "aleatorio"
        elif not estados:
            estado = "sem_imagens"
        else:
            estado = "misto"
        porcor = n / nc
        out.append(LinhaDiagnostico(p.handle, p.nome, p.titulo, p.status, p.cores, p.lados_descricao, n,
                                    f"{porcor:g}", estado, probs, grav))
    return out


def resumo_diagnostico(linhas: List[LinhaDiagnostico], produtos: List[Produto]) -> Dict[str, int]:
    from collections import Counter
    ativos = [l for l in linhas if "produto de teste" not in " ".join(l.problemas)]
    lados = Counter("+".join(l.lados_descricao) or "nenhum" for l in linhas)
    return {
        "produtos": len(linhas),
        "ativos_no_lote": len(ativos),
        "teste_ou_inativos": len(linhas) - len(ativos),
        "azul_marinho_minusculo": sum(1 for p in produtos if "Azul marinho" in p.cores_originais.values()),
        "so_costas": lados.get("costas", 0),
        "frente_e_costas": lados.get("frente+costas", 0),
        "so_frente": lados.get("frente", 0),
        "sem_lado": lados.get("nenhum", 0),
        "nomes_completos": sum(1 for l in linhas if l.estado_nomes == "completo"),
        "nomes_mistos": sum(1 for l in linhas if l.estado_nomes == "misto"),
        "nomes_aleatorios": sum(1 for l in linhas if l.estado_nomes == "aleatorio"),
        "imagens": sum(l.n_imagens for l in linhas),
        "com_problema": sum(1 for l in linhas if l.gravidade != "ok"),
    }
