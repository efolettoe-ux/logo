# PALLACIO — o que falta para gerar todas as camisetas

Situação depois de juntar as 4 pastas de artes (659 arquivos) com o CSV da loja.
Detalhe linha a linha: `dados/mapa.csv` (1 linha por camiseta × cor × lado) e `dados/inventario.csv` (todos os arquivos).
Para conferir com imagens, rode `python3 pallacio.py casar` e abra `revisao.html`.

## Resumo

| | |
|---|---|
| Camisetas ativas no CSV | **169** (a "teste app maxx" ficou de fora) |
| Prontas (todas as cores e lados com arte ou lado liso) | **134** |
| Com arte das costas em pelo menos uma cor | **159** (+ STUDIOS, que só tem frente) |
| Sem nenhuma arte | **9** |
| Faltando a versão de tinta clara ou escura em alguma cor | **12** |
| Faltando a arte da frente (a descrição ou a foto atual mostra estampa na frente) | **23** |
| Linhas do mapa marcadas para revisar | 209 de 1248 |

Posição e tamanho: as 12 camisetas da pasta JA FOI já usam a medida das fotos da loja (`origem=medido`).
As outras usam o padrão (`origem=padrao`, tirado dessas 12 e ajustado à proporção de cada arte).
Depois do `baixar` + `analisar` no Mac, rode `casar` de novo e todas passam a usar a medida real.

## 1. Camisetas sem nenhuma arte (mandar os arquivos)

BRAZILIAN, DJ BOOTH, HERITAGE, JEANS, LOVE IS, NUMBER, PAPA, RULES, TRACK.

- DJ BOOTH: na pasta só tem mockup, não tem o arquivo da estampa.
- HERITAGE: talvez seja o brasão com cavalos "PALLACIO CLUBING" da pasta NOVAS (3 arquivos). Confirmar.
- TRACK: o "I'm that track you skipped" (NOVAS) **não** parece ser a TRACK, que é de carro e track day. Confirmar.

## 2. Falta a versão de tinta para algumas cores

Hoje só existe uma versão. Usar a mesma ficaria ilegível (some no tecido) ou diferente da loja.

| Camiseta | Falta a versão para | Lado |
|---|---|---|
| BACKSTAGE, PERIGNON VERDE, PRETTY | camisa clara (Branca/Off White) | costas |
| PERIGNON ROXA | Off White | costas |
| COTE D' AZUR | camisa clara (e a da loja tem o "Pallacio" dourado; a do arquivo é vermelha) | costas |
| FAKE | camisa escura (Preta/Azul Marinho) | costas |
| FLIRTING, ÁLCOOL | Azul Marinho | costas |
| STAY LATE | Preta | costas |
| EURO SUMMER, FRENCH | camisa clara | frente |
| MARTINI | camisa escura | frente |

Também confira: **LATINA**. O único arquivo tem o texto em branco e "LATINA" em preto. Ele não funciona bem em nenhuma cor (está marcado para revisar).

## 3. Falta a arte da frente

APRÈS SKI, COTE D' AZUR, EXPENSIVE, GARAGE, HOTEL, LE CLUB, LOVE IS, LUXURY, MERCATO, NAUTIC, NUMBER, ORANGE, PAPA, RULES, SICILIAN, STYLE, SUMMER WITH MONEY, TOBACCO, VESPA, ÁLCOOL (todas as cores). EURO SUMMER, FRENCH e MARTINI estão no item 2.

- Na loja, várias dessas frentes são só a assinatura pequena "Pallacio" no peito. Se for a mesma assinatura para todas, basta mandar **um** arquivo dela em duas versões: tinta escura para camisa clara e tinta clara para camisa escura. A assinatura cursiva da CAPRESE ("ChatGPT Image 8 de set. de 2026, 15_09_02" e "15_10_03", em CAMISETAS 100%/ESTAMPAS 100%) talvez sirva. Confirmar.
- LUXURY: as artes "IN BRASIL WE ALL LOVE" (ESTAMPAS PRONTAS P: IZZY, frente e costas) parecem ser dela. Confirmar.
- Se a camiseta não tem frente estampada, escreva `LISO` na coluna `arquivo_estampa` do mapa.csv e `manual` na coluna `origem`.

As fotos atuais de DOLCE, RIVIERA e STICKERS mostram a **frente lisa**, embora a descrição diga "frente e costas". O mapa seguiu a foto (frente lisa).

## 4. Arquivos com problema (estão em uso, mas precisam de correção)

- **Texto errado na arte:**
  - DOMPE: "palacio club" com um L.
  - BLONDE, BRUNETTE, TEXT BACK: "PALACCIO".
  - NAUTIC: "YATCH" e "Principauté de Sonders".
  - YACHT: "YATCH".
  - MONEY TALKS: "Lavish Saint".
  - EXPENSIVE: "Lucchese Studios".
  - SUNRISE: "CLUBING".
  - PLAYING: "PLAYNG".
  - BRASIL MADAME: "BRAZIL".
  - TOBACCO: "Pallácio", com acento.
- **Fundo que não sai limpo** (JPEG com fundo em degradê ou textura), nas versões para camisa clara: AFRO (frente), EURO SUMMER, FRENCH, HOT SEASON (frente e costas), ORANGE e PARADISE (costas). O ideal é PNG com fundo transparente.
- **Cor diferente da loja:** COTE D' AZUR (Pallacio vermelho; na loja é dourado) e BREAK BED na versão para camisa escura (BED/HEART cinza; a descrição pede vermelho).
- **Resolução baixa:** PERIGNON DOURADA frente (único arquivo) e uma cópia do MATCHA, que não foi usada.
- **Formatos que precisam de extra no Mac:** 8 AVIF e 3 SVG. Rode `pip3 install pillow-avif-plugin cairosvg`. Nenhum desses arquivos é a única versão de uma arte.
- **Não são estampas** e o programa ignora: 106 fotos da loja (JA FOI e .webp), 60 mockups de fornecedor, 6 etiquetas de tamanho, 2 fotos lifestyle, 1 print de WhatsApp, 1 foto de outra marca e 1 referência de medidas. A referência diz: logo da frente a 15 cm da gola e com 7 cm de largura.

## 5. Duplicatas ignoradas

64 arquivos marcados como repetidos: 12 cópias idênticas ("- cópia", .jpg = .jpeg) e o resto a mesma arte em outra pasta ou formato.
Ficou sempre a melhor versão: PNG transparente, depois texto correto, depois a pasta ESTAMPAS PRONTAS P: IZZY, depois a maior resolução.
Exceção: quando a foto atual da loja mostra claramente outra versão, vale a da foto. Exemplo: MARTINI costas clara, onde o oval da pasta FOI é igual ao da loja.
A lista está em `revisao.html` e na coluna `duplicata_de` do inventário.

## 6. Artes de produtos que não estão no CSV

I'M THAT TRACK YOU SKIPPED, MULES & DISTRESSED JEANS, ONLY HATE, UNLIMITED CASH, IN BRASIL WE ALL LOVE (talvez LUXURY), PRIVATE SOCIETY/tigre (talvez AVENUE), GIN Hendricks, WINTER WITH MONEY (é moletom), brasão PALLACIO CLUBING (talvez HERITAGE), WELCOME TO AN PALLACIO, WE DO WHAT WE DO, logos soltos (PALLACIO ®CLUB, "PALACIO® CLUB" com um L, "Pallacio, Club", sol + PALLACIO, Logo Sol Vermelho, MADE FOR SUMMER com garrafa).

## 7. O que o dono precisa mandar ou decidir

1. Artes das 9 camisetas do item 1, de preferência em PNG transparente, em duas versões (tinta clara e tinta escura).
2. As versões de tinta que faltam (item 2) e as frentes (item 3). Para as frentes, dizer se é a mesma assinatura "Pallacio" para todas.
3. Corrigir os textos errados (item 4). Em especial "Pallacio" sempre com dois L.
4. Confirmar os palpites: HERITAGE = brasão com cavalos? LUXURY = "In Brasil we all love"? AVENUE = tigre Private Society? PERIGNON, MAGIC, HAPPY, BACKSTAGE, ALREADY LATE e SUMMER usam a mesma tinta em todas as cores?
5. Cores bicolor (AVENUE "Branca / Azul" e "Branca / Preta", BRING "Branca / Azul Claro" e "Branca / Azul Escuro", DJ BOOTH "Preta / Vermelha"): precisam de mockup próprio. Sem ele ficam como `sem_mockup`.
