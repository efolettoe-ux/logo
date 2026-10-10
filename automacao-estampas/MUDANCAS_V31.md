# O que mudou da v3 para a v3.1 (fotos de modelo)

## Fidelidade da arte (todas as estampas)
- **Recorte fiel do PNG oficial:** o carregador antigo jogava fora 0,15% da tinta em cada ponta da
  arte e cortava floreios e pontas de letras. Isso acontecia em 406 das 420 artes PNG e afetava
  também os mockups lisos e a v2. Agora só saem as margens transparentes e pontinhos realmente
  soltos. Os pixels da arte são idênticos ao PNG (conferido).
- **Uma amostragem só:** a v3 reduzia a arte para a caixa do mockup (cerca de 200 px), deformava
  de novo e ainda aplicava desfoque. Agora a arte vai do PNG original direto para a foto: uma
  redução por área para cerca de 3 a 4 vezes o tamanho final, a transformação nessa grade e uma
  redução final por área. Sem desfoque extra.

## Logo pequena da frente
- **Transformação mínima:** giro (inclinação dos ombros), escala e um leve achatamento de
  perspectiva só na horizontal. Sem deformação local, sem dobras e sem deslocar letra:
  a caligrafia não muda.
- **Posição equilibrada no peito:** o centro fica na mesma fração do meio tronco em todas as
  fotos (0,40, a média das frentes aprovadas), com a altura da v2 aprovada. Assim a logo não vai
  mais para perto da manga (off-white close).
- **Luz só suave e trama de 0,5%:** a tinta acompanha a luz da camiseta sem manchar as letras.

## Estampa grande das costas
- **Altura igual à v2 aprovada:** o topo da estampa fica onde estava na v2, foto por foto
  (`dados/referencia_v2_posicao.json`). Tamanho e proporção continuam os da v3, sem mudança.
- **Dobras localizadas:** a estampa só se desloca onde há dobra de verdade, proporcional à força
  da dobra e no máximo 2 px. Antes, toda foto recebia o mesmo deslocamento máximo.
- **Luz real da camiseta:** o cálculo foto ÷ cor do tecido ganhou uma margem para tecido escuro,
  então sombra e brilho do preto não explodem na tinta. A luz é filtrada acima do ruído da trama.
- **Trama sutil e igual em todas as cores (0,8%):** sem porosidade nem aspecto desgastado, e sem
  desfoque na borda (o antisserrilhado vem da amostragem).

## Pontos do corpo e validação
- **Ombro medido depois da axila:** a altura da axila é corrigida primeiro, e o ombro passa a ser
  medido em cima dela, não mais na gola.
- **Validação antes de gerar** (`validar_pontos`): confere se a gola está entre os ombros, se cada
  ombro está em cima da sua axila, a ordem vertical ombro > axila > lateral > barra, a inclinação
  dos ombros e a proporção do tronco. Foto com ponto incoerente não é gerada.
- **Foto 8 (branca, frente, corpo inteiro):** a validação barrou a foto, porque o ombro esquerdo
  caía na gola. Os pontos manuais estão em `dados/pontos_manuais.json`; com eles ela passa.

## Preservação
- **Fora da tinta, nada muda:** os pixels são cópia exata da foto base. A conferência roda em toda
  imagem gerada e deu 0 nas 7 fotos. As fotos originais e as versões aprovadas não foram tocadas.
- **Foto base:** é a foto do modelo com a cor do tecido igual ao mockup (já aprovada antes).

## Amostra
`amostras/v3.1-completa/`: CAPRESE em 7 fotos (as 6 da v3 + foto 8), mais
`comparacao_v2_v3_v31.jpg`, `zoom_costas_v3_v31.jpg` e `registro_CAPRESE.json` (arquivo exato
usado em cada foto e a conferência dos pixels).
