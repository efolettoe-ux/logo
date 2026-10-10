# Diagnóstico do sistema de estampas nas fotos de modelo e motor v3 (OpenCV)

## 1. Arquivos disponíveis (conferidos)

| Item | Situação |
|---|---|
| Fotos de modelo (16 PNG, 1344×2400, fundo transparente) | Completas, idênticas byte a byte ao zip original `PNG_MOCKUP_MODELOS.zip`; os originais não foram alterados |
| Artes das estampas | 498 arquivos referenciados no `mapa.csv`, todos abrem; 0 faltando, 0 corrompidos (468 linhas são frente lisa) |
| `mapa.csv` | 1.248 linhas, 169 produtos |
| Mockups lisos de referência | 15 PNG (5 cores: frente, costas e close-costas) + inclinadas |
| Mockups lisos finais (aprovados) | 1.864 PNG |
| Fotos de modelo v2 (entregues) | 2.476 PNG (branches `modelos-*`) |
| Zips enviados | 4 zips testados, sem erro |
| Git LFS | Não é usado no repositório (não há `.gitattributes`); nada pendente |
| `LEIA-ME.md` | **Não existe** em nenhum branch do repositório nem no ambiente. O que existe: `README.md`, `PROMPT_CODEX_REALISMO.md` e `automacao-modelos/PROMPT_CODEX.md` |

O repositório não tem branch `main`. O branch padrão é `claude/upbeat-heisenberg-t0tcbn`, que tem o trabalho de logos e não foi tocado. Este trabalho está só em `claude/hopeful-bell-3r8wql`.

## 2. Por que o sistema anterior (v2) não ficou realista

Medido nas fotos, não é só impressão visual:

1. **"Deslocar" errado: mexia a estampa inteira, não as dobras.** O mapa usava o brilho absoluto
   da foto. Numa camiseta branca isso dava um desvio médio de **+9,6 px** e na preta de **−10,7 px**
   na diagonal, enquanto as dobras de verdade só moviam **±0,6 a 1,5 px**. Resultado: a posição
   mudava conforme a cor, e as dobras quase não apareciam. Isso explica parte dos ajustes foto a
   foto pedidos nas revisões.
2. **Posição e escala sem referência fixa.** O tronco foi medido à mão em cada foto (±30 px), e a
   linha da gola chegou a ter erros de 15 a 40 px. Cada foto precisou de correções manuais, porque
   não havia ligação geométrica com o mockup liso.
3. **Curvatura simplificada.** O tronco era um cilindro com mistura arco/plano. Na prática, o meio
   das costas e do peito é quase plano e a curvatura fica nas laterais (corte elíptico). Por isso a
   estampa ficava menor do que deveria em relação à largura visível, e você pedia "15% maior".
4. **Perspectiva e inclinação manuais.** A inclinação dos ombros não era medida, então foi
   preciso girar o logo à mão (de 3° a 16°).
5. **Textura relativa ao brilho.** A trama era dividida pelo brilho local, o que a deixava
   **7 a 10 vezes mais forte** em camiseta escura (azul-marinho 5,8%, preta 7,6%) do que na clara
   (0,8%). Foi o "muita textura" no azul e na preta.
6. **Iluminação diferente por cor.** Na clara era Multiplicar e na escura uma sombra comprimida
   (`^0,6`, limitada a 0,6–1,4): as dobras não se comportavam igual nas cores.

## 3. Motor v3 (`motor_v3.py`, OpenCV, sem IA)

1. **Pontos da camiseta automáticos:** ombros, axilas, laterais, barra e linha da gola, achados
   pelo contorno e pelos defeitos de convexidade (OpenCV), com o mesmo método no mockup liso e na
   foto. A altura da axila segue a proporção do mockup, porque na foto o braço está abaixado.
2. **Mockup liso como referência:** a caixa da estampa sai do mockup liso aprovado.
   - **Posição:** mesma proporção do comprimento da camiseta (ombros → barra), e o
     deslocamento lateral vira arco no tecido.
   - **Tamanho:** escala do meio do tronco, a mesma na horizontal e na vertical, então a arte não
     achata nem estica.
3. **Curvatura:** corte elíptico do tronco (profundidade ≈ 65% da largura) com o giro do corpo
   tirado da linha da gola. Acompanha também a inclinação dos ombros.
4. **Dobras:** deslocamento pelo gradiente das dobras de média frequência, com média zero. A
   estampa entorta nas dobras e não anda inteira.
5. **Luz:** tinta = cor da arte × iluminação do tecido (foto ÷ cor do tecido), em luz linear e
   igual para todas as cores. A iluminação é filtrada acima do ruído da trama (bilateral), então
   ficam só as dobras.
6. **Textura:** trama com amplitude fixa (1,2%), igual em camiseta clara e escura.
7. **Oclusão:** braço e mão por cima da estampa. A cor da camiseta igual ao mockup foi mantida
   (já aprovada).

## 4. Amostra de teste

Está em `amostras/v3/` e não sobrescreve nada: CAPRESE em 6 fotos (4 cores, 4 vistas) e
`comparacao_v2_v3.jpg`, com v2 e v3 lado a lado. O catálogo completo **não** foi processado.

Pontos em aberto antes de rodar o catálogo:
- Na foto 8 (branca, frente, corpo inteiro, modelo virado) o ponto do ombro esquerdo cai na gola.
  Precisa de ponto manual (`pontos_manuais.json`).
- Logo da frente perto da manga (off-white close): ele encolhe na lateral, como numa camiseta de
  verdade. Se preferir mais perto do centro, isso é um ajuste de referência, não de foto.
- A altura agora segue o mockup liso. As costas ficaram um pouco mais baixas do que na v2 aprovada
  (v2: topo a 8,6% do comprimento; mockup liso: 13%).
