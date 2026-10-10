# Padrão de nomes das imagens finais PALLACIO (para o Codex)

Use estas regras para organizar, renomear ou gerar as imagens finais. Não altere as imagens: só
copie e renomeie, byte a byte.

## 1. Formato do nome

```
PALL-{PRODUTO}-{COR}_{NN}-{descrição}.png
```

| Parte | Regra | Exemplo |
|---|---|---|
| `PALL-` | prefixo fixo | `PALL-` |
| `{PRODUTO}` | coluna `NOME` do `mapa.csv`, em maiúsculas, palavras separadas por hífen | `CAPRESE`, `8-BILLION`, `AMALFI-COAST` |
| `{COR}` | código da cor (tabela abaixo) | `PT` |
| `_` | separa produto/cor da numeração | `_` |
| `{NN}` | número do mockup com 2 dígitos, de `01` a `07` | `04` |
| `{descrição}` | tipo da imagem (tabela da seção 3) | `modelo-costas-close` |
| `.png` | sempre PNG com fundo transparente | `.png` |

Exemplo completo: `PALL-CAPRESE-PT_04-modelo-costas-close.png`

### Códigos de cor

| Cor (`mapa.csv`) | Código |
|---|---|
| Azul Marinho | `AZ` |
| Branca | `BR` |
| Off White | `OW` |
| Preta | `PT` |
| Branca / Azul Claro | `BR-AZC` |
| Branca / Azul Escuro | `BR-AZE` |
| Branca / Azul | `BR-AZL` |
| Branca / Preta | `BR-PT` |
| Preta / Vermelha | `PT-VM` |

## 2. Como saber o caso de cada camiseta

Olhe o `mapa.csv` para o par produto + cor:
- `arquivo_estampa` da linha `lado = frente` diferente de `LISO` e da linha `lado = costas` diferente de `LISO`: **frente e costas**.
- Só costas com arte (frente `LISO`): **só costas**.
- Só frente com arte (costas `LISO`): **só frente** (hoje só a STUDIOS).

## 3. Numeração por caso

### Frente e costas
| NN | descrição | O que é | Arquivo de origem |
|---|---|---|---|
| 01 | `costas` | mockup padrão, costas | `PALL-{P}-{C}_01-costas.png` (branch `mockups-finais`) |
| 02 | `frente` | mockup padrão, frente | `PALL-{P}-{C}_02-frente.png` |
| 03 | `close` | close padrão (foto inclinada) | `PALL-{P}-{C}_03-inclinada.png` |
| 04 | `modelo-costas-close` | modelo, close de costas | `PALL-{P}-{C}_M1-costas-close.png` (branches `modelos-*`) |
| 05 | `modelo-frente-close` | modelo, close de frente | `PALL-{P}-{C}_M2-frente-close.png` |
| 06 | `modelo-costas-corpo` | modelo, corpo inteiro de costas | `PALL-{P}-{C}_M3-costas-corpo.png` |
| 07 | `modelo-frente-corpo` | modelo, corpo inteiro de frente | `PALL-{P}-{C}_M4-frente-corpo.png` |

### Só costas
| NN | descrição | O que é | Arquivo de origem |
|---|---|---|---|
| 01 | `costas` | mockup padrão, costas | `_01-costas.png` |
| 02 | `close` | close padrão (foto inclinada) | `_03-inclinada.png` |
| 03 | `frente` | mockup padrão, frente sem estampa | `_02-frente.png` |
| 04–07 | iguais ao caso anterior | modelo | `_M1` … `_M4` |

### Só frente (STUDIOS)
| NN | descrição | O que é | Arquivo de origem |
|---|---|---|---|
| 01 | `frente` | mockup padrão, frente | `_01-frente.png` |
| 02 | `costas` | mockup padrão, costas lisa | o próprio mockup liso de costas da cor (sem estampa) |
| — | — | não tem 03 | — |
| 04–07 | iguais aos outros casos | modelo | `_M1` … `_M4` |

Regras fixas:
- 04, 05, 06 e 07 são sempre os mesmos enquadramentos do modelo, em qualquer caso.
- Bicolores (`BR-AZC`, `BR-AZE`, `BR-AZL`, `BR-PT`, `PT-VM`) não têm foto de modelo: só 01 a 03.

## 4. Exemplos

```
PALL-CAPRESE-PT_01-costas.png               (frente e costas)
PALL-CAPRESE-PT_02-frente.png
PALL-CAPRESE-PT_03-close.png
PALL-CAPRESE-PT_04-modelo-costas-close.png
PALL-CAPRESE-PT_05-modelo-frente-close.png
PALL-CAPRESE-PT_06-modelo-costas-corpo.png
PALL-CAPRESE-PT_07-modelo-frente-corpo.png

PALL-8-BILLION-BR_01-costas.png             (só costas)
PALL-8-BILLION-BR_02-close.png
PALL-8-BILLION-BR_03-frente.png
PALL-8-BILLION-BR_04-modelo-costas-close.png ... _07-modelo-frente-corpo.png

PALL-STUDIOS-PT_01-frente.png               (só frente)
PALL-STUDIOS-PT_02-costas.png
PALL-STUDIOS-PT_04-modelo-costas-close.png ... _07-modelo-frente-corpo.png

PALL-AVENUE-BR-AZL_01-costas.png            (bicolor, só costas, sem modelo)
PALL-AVENUE-BR-AZL_02-close.png
PALL-AVENUE-BR-AZL_03-frente.png
```

## 5. Onde está tudo

- Tabela completa (4.344 linhas: branch, arquivo de origem e nome final):
  `mapa_drive.csv` no branch `drive-organizacao`.
- Imagens já renomeadas, numa pasta única por cor: branches `finais-azul-marinho`,
  `finais-branca`, `finais-off-white` e `finais-preta`.
- Total: 4.344 imagens. Por caso: 156 frente e costas, 464 só costas, 4 só frente.
- Conferência: nenhum nome repetido. Todo arquivo final tem origem.
