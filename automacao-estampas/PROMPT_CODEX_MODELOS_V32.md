# Prompt para o Codex: fotos de modelo de todas as estampas (motor v3.2, igual à CAPRESE aprovada)

Cole o bloco abaixo no Codex junto com o zip.

```text
Você vai gerar as fotos de modelo (4 por cor) de TODAS as estampas da PALLACIO usando o motor que já
está pronto e aprovado (v3.2, Python + OpenCV). A CAPRESE está 100% aprovada: as outras estampas têm que
sair com a MESMA lógica, sem reinventar nada. Você NÃO escreve um motor novo: só configura as pastas,
roda, confere e entrega.

REGRAS (obrigatórias)
1. Não use IA generativa. Não redesenhe, recrie ou reinterprete textos, letras ou logos.
2. Use só os PNG/JPEG originais das estampas, associados pelo mapa.csv (coluna arquivo_estampa).
3. Não altere os arquivos originais (fotos dos modelos, estampas, mockups lisos). Escreva só na pasta de saída.
4. Pixels fora da estampa têm que ficar idênticos à foto base: o script confere
   (pixels_alterados_fora_da_tinta = 0). Foto com valor diferente de 0 NÃO é entregue.
5. Não mude parâmetros do motor (desfoque 0,55/0,35 px, dessaturação 5%, faixa de tons, textura 0,8%/0,5%,
   dobras máx. 2 px). NÃO use ACABAMENTO=1 (isso é a v3.3, que não foi aprovada).
6. Nada vai para a Shopify.

CONTEÚDO DO ZIP
- codigo/: motor_v3.py (motor), amostra_v31.py (gera as fotos de 1 produto), rodar_catalogo_modelos.py
  (roda todos e renomeia), e os módulos que eles importam (modelos.py, imagem.py, compositor.py, catalogo.py...).
- codigo/dados/: tudo que é fixo por foto, já aprovado na CAPRESE:
  - torsos_modelos.json, topos.json: medidas do tronco de cada uma das 16 fotos;
  - pontos_manuais.json: pontos corrigidos à mão (foto branca-frente-corpo);
  - referencia_v2_posicao.json: posição aprovada da estampa das costas em cada foto;
  - ajustes_v31.json: giro extra do logo da frente (6° em 4 fotos);
  - calibracao_caprese.json: âncora, escala e posição da CAPRESE em cada foto. É isso que faz as outras
    estampas caírem na MESMA posição relativa que têm no seu mockup liso (uma estampa maior/mais alta no
    mockup liso fica maior/mais alta na foto). NÃO apague nem recalcule, a não ser rodando a CAPRESE.
  - cores_mockup.json: cor de cada camiseta (igual ao mockup liso);
- fotos_modelo/: as 16 fotos originais dos modelos (1344x2400, fundo transparente). Nomes:
  {cor}-{costas|frente}-{close|corpo}.png, cores: azul-marinho, branca, off-white, preta.
- base/mockups/: mockups lisos sem estampa por cor (para achar a caixa da estampa no mockup liso).
- base/mk5/: mockups de referência para os pontos do tronco.
- base/mapa.csv: produto, cor, lado, arquivo da estampa.
- aprovado_v32/: as 16 fotos CAPRESE aprovadas, a folha das 16, o zoom v3.1 x v3.2 e 5 fotos maiores.
  É o padrão de qualidade: o resultado das outras estampas tem que ter o mesmo aspecto.

O QUE FALTA NO ZIP (já está no seu computador)
- As artes originais (pasta com as subpastas citadas no mapa.csv, ex.: "NOVAS/...", "CAMISETAS 100%/...").
- Os mockups lisos finais aprovados (PALL-{PRODUTO}-{COR}_01-costas.png e _02-frente.png, branch
  mockups-finais). O motor usa eles só para ler a posição e o tamanho da estampa.

COMO A LÓGICA FUNCIONA (para você entender, não para mudar)
1. Pontos do tronco (ombros, axilas, laterais, barra, gola) achados pelo contorno da camiseta, na foto e no
   mockup liso; pontos incoerentes são recusados (a foto não é gerada e vai para o relatório).
2. A caixa da estampa sai do mockup liso aprovado daquele produto/cor.
3. Costas (estampa grande): a arte é levada direto do PNG para a foto numa única amostragem (supersampling),
   seguindo a curvatura do tronco (elipse, profundidade 0,65) e o giro do corpo. Âncora/escala/posição =
   calibração da CAPRESE em cada foto.
4. Frente (logo pequena): transformação mínima (escala, rotação do ombro, perspectiva leve), sem deformar letra.
   Centro = calibração da CAPRESE + giro extra das 4 fotos de ajustes_v31.json.
5. Tinta: cor da arte x luz real da camiseta (dobras), deslocamento só nas dobras (máx. 2 px), trama sutil
   fixa, tons dentro da faixa da foto, 5% menos saturação, suavidade de câmera 0,55 px (costas) / 0,35 px (frente).
6. Lado LISO no mapa.csv: a foto sai com a camiseta lisa na cor certa.

PASSO A PASSO
1. Python 3.10+: pip install numpy scipy pillow opencv-python-headless
2. Configure as pastas (variáveis de ambiente):
     PALLACIO_DIR=<zip>/base            (tem mapa.csv e mockups/)
     ESTAMPAS_DIR=<pasta das artes originais>
     LISOS_DIR=<pasta com os mockups lisos finais>  (aceita subpasta por produto ou pasta única)
     FOTOS_DIR=<zip>/fotos_modelo
     MOCKUPS_PONTOS_DIR=<zip>/base/mk5
3. Teste de conferência (obrigatório): rode a CAPRESE e compare com aprovado_v32/. Tem que dar
   IGUAL pixel a pixel nas 16 fotos:
     SAIDA_V31=teste_caprese INTEGRA=1 python3 codigo/amostra_v31.py CAPRESE azul-marinho-costas-close,...(as 16)
   Se não der igual, PARE e descubra a diferença (versão de biblioteca, pasta errada) antes de seguir.
4. Teste em 3 estampas diferentes (uma grande colorida, uma só de texto, uma só costas), por exemplo:
     python3 codigo/rodar_catalogo_modelos.py saida_teste AFRO,8-BILLION,AMALFI-COAST
   Confira visualmente: posição igual à da CAPRESE em relação ao mockup liso, sem letra deformada.
   Mostre para o dono e só siga com a aprovação dele.
5. Catálogo completo:
     python3 codigo/rodar_catalogo_modelos.py saida_modelos
   Gera PALL-{PRODUTO}-{COR}_04-modelo-costas-close.png, _05-modelo-frente-close, _06-modelo-costas-corpo,
   _07-modelo-frente-corpo, todos numa pasta única, PNG com fundo transparente na resolução original.
   O relatório está em saida_modelos/_relatorio_modelos.json: liste os produtos com problema
   (foto não gerada, arte faltando, pixel fora da tinta) e NÃO invente correção: pergunte.

NOMES (padrão da loja; ver NOMES_ARQUIVOS_CODEX.md)
PALL-{PRODUTO}-{COR}_{NN}-{descrição}.png, COR: AZ, BR, OW, PT. 04 a 07 são sempre as fotos de modelo.
Bicolores não têm foto de modelo.
```
