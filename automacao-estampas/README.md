# PALLACIO: estampas nos mockups lisos

Este programa coloca a arte original de cada camiseta nos mockups lisos. A estampa sai no mesmo tamanho
e na mesma posição que tem hoje na loja, com a luz, as dobras e a textura do mockup. Nada é gerado por
IA: o fundo é sempre o seu mockup e a arte é o seu arquivo.

Fotos de cada camiseta e cor, com os nomes no padrão da loja:

| Nº | Foto | Exemplo |
|---|---|---|
| 01 | costas reta (principal) | `PALL-CAPRESE-PT_01-costas.png` |
| 02 | frente reta | `PALL-CAPRESE-PT_02-frente.png` |
| 03 | costas inclinada | `PALL-CAPRESE-PT_03-inclinada.png` |

Quando a camiseta só tem estampa na frente, a frente vira a 01 e não há foto inclinada.

## 1. Instalar (uma vez)

1. Instale o Python 3 pelo site python.org (versão para Mac).
2. Abra o **Terminal** e rode:
   ```
   pip3 install pillow numpy
   ```
   Para ler AVIF e SVG, rode também `pip3 install pillow-avif-plugin cairosvg`.
3. Se o `baixar` der erro de certificado (`CERTIFICATE_VERIFY_FAILED`), abra a pasta
   `/Applications/Python 3.x/` e dê dois cliques em **Install Certificates.command**.

## 2. Organizar a pasta do projeto

```
PALLACIO/                      ← pasta do projeto (use --pasta para apontar para ela)
├── products_export_1.csv      ← export de produtos do Shopify
├── config.json                ← criado sozinho na primeira vez
├── mockups/                   ← mockups lisos, PNG com fundo transparente
│   ├── preta-costas.png
│   ├── preta-frente.png
│   ├── preta-costas-inclinada.png
│   └── … (branca, off-white, azul-marinho, chumbo)
└── as pastas de artes como estão (CAMISETAS 100%, NOVAS, ESTAMPAS PRONTAS…, MATERIAL QUALITY 100%)
```

O nome do mockup diz a cor e a vista: `{cor}-frente`, `{cor}-costas` ou `{cor}-costas-inclinada`.
O chumbo está desligado no `config.json` (`"ativa": false`).

## 3. Rodar (nesta ordem)

No Terminal, entre na pasta do programa. Digite `cd `, arraste a pasta `automacao-estampas` para a
janela e aperte Enter. Depois rode os comandos, trocando `PASTA` pela pasta do projeto:

| Comando | O que faz |
|---|---|
| `python3 pallacio.py diagnostico --pasta PASTA` | Lista os problemas do CSV (cores, produto de teste…). |
| `python3 pallacio.py baixar --pasta PASTA` | Baixa as fotos atuais da loja (cerca de 1.200, uns 5 min). |
| `python3 pallacio.py analisar --pasta PASTA` | Mede o tamanho e a posição da estampa em cada foto (~3 min). |
| `python3 pallacio.py casar --pasta PASTA` | Liga cada arte ao produto, à cor e ao lado. Gera o `mapa.csv` e o `revisao.html`. |
| *abrir `revisao.html`* | Confira as linhas marcadas para revisar. Para corrigir, edite o `mapa.csv` e escreva `manual` na coluna `origem`, assim a correção não é sobrescrita. |
| `python3 pallacio.py estampar --pasta PASTA --mockups PASTA/mockups --limite 3 --previa` | Teste rápido em baixa resolução. |
| `python3 pallacio.py estampar --pasta PASTA --mockups PASTA/mockups` | Gera tudo. Rodar de novo pula o que já existe (use `--forcar` para refazer). |

Onde ficam os resultados:
- `saida_web/`: JPGs de até 2048px, prontos para o Shopify;
- `saida/`: PNG em resolução cheia;
- `relatorio.csv`: o que foi gerado, o que falta e por quê;
- `folha_contato.jpg` e `antes_depois.html`: para conferir o resultado.

Para subir no Shopify: vá em **Conteúdo → Arquivos** e envie os JPGs de `saida_web/` sem renomear.

## 4. Ajustes comuns

- **Arte nova:** coloque o arquivo numa das pastas de artes, rode `casar` e depois `estampar`.
- **Frente sem estampa:** escreva `LISO` em `arquivo_estampa` no `mapa.csv`.
- **Estampa um pouco grande ou pequena em um produto:** ajuste `largura_rel` no `mapa.csv`.
- **Mockup novo:** se for só uma cor nova, basta colocar os PNGs na pasta `mockups/`. Se for outro
  ângulo, use o `calibrador.html` (abra com dois cliques) para marcar o tronco da camiseta.
- **Foto do close das costas:** em `config.json`, mude `"usar_close"` para `true`. Ela entra como 04.

O que falta de arte está em `dados/lacunas.md`.
