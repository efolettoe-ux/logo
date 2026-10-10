# Prompt para o Codex: estampa realista em foto de modelo/mockup

Cole o bloco abaixo no Codex. Ele explica como aplicar uma estampa (PNG) numa foto de camiseta
(PNG com fundo transparente) para que ela pareça impressa no tecido: acompanhar a curvatura do
corpo, o ângulo, as dobras/ondas e a trama, com a cor da camiseta igual ao mockup. A posição e o
tamanho da estampa ficam de fora: o script recebe a caixa (x, y, largura, altura) pronta.

```text
Você é um engenheiro Python. Crie `estampar_realista.py` (Pillow + numpy + scipy, sem IA, sem GPU)
com uma função:

    aplicar(foto_png, estampa_png, caixa, tronco, gola_x, cor_mockup=None, realismo=0.5,
            textura_escura=0.25) -> PNG RGBA

- foto_png: foto da camiseta (pessoa ou mockup) com fundo transparente. O alfa da foto é mantido.
- estampa_png: arte com fundo transparente (ou JPG com fundo liso: remova o fundo antes).
- caixa: (x, y, largura, altura) da estampa na foto, já decidida. NÃO calcule posição.
- tronco: (x0, x1, topo, barra) do tronco da camiseta na foto, em px. Usado só para a curvatura.
- gola_x: x do centro da gola (linha do esterno/coluna). Indica se o corpo está virado.
- cor_mockup: (R,G,B) da camiseta no mockup de referência. Se vier, a camiseta é recolorida.

Passos, nesta ordem:

1. MÁSCARAS
   - pele: pixels de pele (tons quentes; ex.: em YCrCb, Cr 135–180 e Cb 85–135), dilatada 3 px.
     Onde é pele (braço/mão na frente do corpo) a estampa NÃO aparece (oclusão).
   - camiseta (para recolorir): silhueta da pessoa (alfa > 20) MENOS pele, só entre topo-40 e
     barra+40. Na metade de baixo, cada pixel vai para "camiseta" ou "calça" pela cor mais próxima
     (Lab, pesos L 0.3, a 1.5, b 1.5; referência da calça = mediana da faixa barra+40..barra+160).
     Também tira o que estiver mais perto da cor da pele (sombra do braço). Abra/feche 2–3 px,
     fique só com o maior pedaço, preencha buracos, desfoque gaussiano 1.2 px (borda suave).

2. COR DO TECIDO IGUAL AO MOCKUP (se cor_mockup)
   - Converta a foto para luz LINEAR (sRGB -> linear).
   - ganho por canal = linear(cor_mockup) / mediana linear da camiseta (pixels com máscara > 0.8).
   - novo = linear * ganho; misture com a foto pela máscara suave; volte para sRGB.
   Assim luz, sombra, dobras e trama continuam iguais; só o tom muda.

3. CURVATURA (estampa enrolada no corpo, não plana como uma prancha)
   - Trate o tronco como um cilindro: R = (x1-x0)/2, centro cx = (x0+x1)/2.
   - giro do corpo: g = arcsin((gola_x - cx)/R), limitado a ±0.6 rad.
   - Para cada coluna plana s da estampa (distância até a gola), o ângulo no cilindro é
     teta(s) = 0.55*arcsin(s/(R*cos g)) + 0.45*s/R, e o x na foto é cx + R*sin(g + teta(s)).
     Resultado: no meio fica do tamanho certo, perto das laterais encolhe, e o lado mais longe
     encolhe mais quando o corpo está virado.
   - Caimento: as pontas descem um pouco: dy = 0.025*altura*u² (u = -1..1 a partir da gola).
   - Faça o mapeamento inverso (para cada pixel de destino, ache u, v de origem por interpolação),
     amostragem bilinear, trabalhando em 2x e reduzindo com LANCZOS no fim.

4. DOBRAS E ONDAS (o "Deslocar 10 x 10" do Photoshop)
   - Mapa = foto em tons de cinza, desfocada 2 px (gaussiano).
   - deslocamento d = (mapa - 0.5) * 2 * D, com D = 10 + 6*realismo px.
   - Amostre a estampa em (y - d, x - d): ela entorta junto com as dobras.

5. LUZ E SOMBRA (modo de mesclagem)
   - Camiseta clara (média da cor do tecido > 0.45): MULTIPLICAR: tinta = cor_estampa * foto.
   - Camiseta escura: multiplicar apagaria a tinta. Use sombra relativa ao tecido:
       lum = média RGB da foto; em camiseta escura suavize a trama antes:
       liso = gaussiano(lum, 2); lum = liso + textura_escura*(lum - liso)
       rel = clip((lum / cor_tecido_média) ** 0.6, 0.6, 1.4); tinta = cor_estampa * rel
     (dobra funda escurece a tinta, mas não some com ela).

6. TINTA DE VERDADE (realismo, 0..1; use 0.5)
   - hp = clip((lum - gauss(lum, 2.5)) / max(gauss(lum, 2.5), 0.04), -0.35, 0.35)
     (trama/dobra fina). Em camiseta escura multiplique hp por textura_escura (0.25).
   - alfa *= 1 - realismo*(0.9*max(-hp, 0) + 0.06*textura*|grão|)
     (grão = ruído gaussiano com semente fixa, desfocado 0.7 px): tinta mais fina nos poros.
   - alfa = gaussiano(alfa, 0.35*realismo): borda de tinta, não recorte.
   - tinta *= 1 + realismo*k*hp (k = 1.2 em camiseta escura, 0.4 em clara): trama por cima.
   - Em camiseta clara: partes da arte quase da cor do tecido (sobra de fundo creme/branco)
     não são impressas: alfa *= clip((max|cor - tecido| - 0.07)/0.08, 0, 1).

7. COMPOSIÇÃO
   - alfa *= (1 - pele); saída = foto*(1-alfa) + tinta*alfa; mantenha o alfa ORIGINAL da foto.
   - Redimensione a estampa com alfa PRÉ-MULTIPLICADO (evita borda escura/clara) e LANCZOS.
   - Salve PNG RGBA na resolução original da foto.

Entregue também `testar.py`: aplica uma estampa de teste em 2 fotos (uma clara e uma escura) e
salva lado a lado com recortes em zoom (estampa, borda, dobra) para conferir.
```

## Valores que funcionaram (PALLACIO)

| Parâmetro | Valor |
|---|---|
| Deslocamento (Deslocar) | 10 + 6×realismo px, mapa desfocado 2 px |
| Curvatura | mistura 0.55 (arco) / 0.45 (plano), caimento 0.025 |
| Sombra em camiseta escura | rel^0.6, limitado 0.6–1.4 |
| Realismo | 0.5 (V2) |
| Textura em camiseta escura | 25% |
| Cores do mockup | branca 244,244,244 · off-white 241,234,221 · preta 15,15,16 · azul-marinho 22,34,60 · chumbo 49,48,50 |
