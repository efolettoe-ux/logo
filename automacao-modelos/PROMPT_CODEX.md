# Automação: estampas nas fotos de modelo (PALLACIO)

## Parte 1 — Explicação do zero

### O que vamos fazer
1. Você gera **~6 fotos base** do modelo vestindo peças **lisas** (ChatGPT/Gemini):
   camiseta branca/preta e hoodie branco, cada uma de **frente** e **costas**.
2. Um script em Python aplica **cada estampa** na foto base certa, para **todos os produtos** do CSV, sozinho.
3. Resultado: uma pasta com todas as fotos prontas, todas no mesmo padrão.

### O que você precisa instalar (uma vez)
1. **Python 3.11+** → https://www.python.org/downloads/ (no Windows marque **"Add Python to PATH"**).
2. **VS Code** → https://code.visualstudio.com/
3. **Codex** → extensão "Codex" no VS Code (ou Codex CLI: `npm i -g @openai/codex`), logado na sua conta ChatGPT.

### Monte a pasta do projeto assim
```
pallacio-modelos/
├── products_export_1.csv          ← export do Shopify
├── bases/                         ← fotos base do modelo (você gera)
│   ├── tshirt_branca_frente.png
│   ├── tshirt_branca_costas.png
│   ├── tshirt_preta_frente.png
│   ├── tshirt_preta_costas.png
│   ├── hoodie_branca_frente.png
│   └── hoodie_branca_costas.png
├── estampas/                      ← PNG transparente de cada estampa
│   ├── track_frente.png
│   ├── track_costas.png
│   └── ...
└── saida/                         ← o script cria e preenche
```
Regras de nome:
- Bases: `{tipo}_{cor}_{lado}.png` → tipo = `tshirt` ou `hoodie`; cor sem acento, minúscula; lado = `frente` ou `costas`.
- Estampas: `{handle}_{lado}.png`, onde `handle` é a coluna **Handle** do CSV (ex.: `track-t-shirt_frente.png`).
  Se a estampa muda com a cor da peça (ex.: arte preta pra camiseta branca), use `{handle}_{cor}_{lado}.png`.

### Passo a passo
1. Abra a pasta `pallacio-modelos` no VS Code.
2. Abra o Codex e cole o **prompt da Parte 2** inteiro.
3. Deixe ele criar os arquivos e rodar. Quando pedir permissão para instalar pacotes/rodar comandos, aceite.
4. Rode a calibração: `python calibrar.py` → abre as bases com um retângulo mostrando onde a estampa vai.
   Ajuste os números no `config.yaml` até o retângulo ficar certinho no peito/costas.
5. Teste com poucos produtos: `python aplicar.py --limite 5` → confira a pasta `saida/`.
6. Gere tudo: `python aplicar.py`.
7. Produto novo no futuro: coloque a estampa em `estampas/` e rode `python aplicar.py` de novo (ele pula o que já existe).

---

## Parte 2 — Prompt para colar no Codex

```text
Você é um engenheiro Python. Crie, nesta pasta, uma automação que aplica estampas (PNG transparente) em fotos base de um modelo vestindo roupas lisas, para todos os produtos de um export CSV do Shopify. Crie os arquivos, instale dependências, rode os testes e me mostre o resultado.

## Contexto
- Marca de moda masculina. Produtos: camisetas (Type = "T-Shirt") e moletons (Type = "Hoodie").
- `products_export_1.csv` é o export padrão do Shopify: várias linhas por produto. A linha com "Title" preenchido é a principal; as outras são variantes/imagens do mesmo "Handle". Colunas relevantes: Handle, Title, Type, Option1 Name/Value, Option2 Name/Value, Option3 Name/Value.
- A cor está na opção cujo nome contém "cor" ou "color" (sem diferenciar maiúsculas). Valores atuais: "Branca", "Preta", "Branca / Preta", "Branca / Azul Escuro". Normalize: minúsculo, sem acento, espaços e "/" viram "-" (ex.: "branca-preta").
- Fotos base em `bases/{tipo}_{cor}_{lado}.png` (tipo: tshirt|hoodie; lado: frente|costas).
- Estampas em `estampas/`. Procurar nesta ordem: `{handle}_{cor}_{lado}.png`, depois `{handle}_{lado}.png`. Se não houver estampa para um lado, gerar aquele lado com a peça lisa só se `gerar_sem_estampa: true` no config; senão pular.

## Arquivos a criar
1. `requirements.txt`: pillow, numpy, opencv-python, pyyaml, tqdm.
2. `config.yaml` com, para cada base (tipo+lado), a área de impressão:
   - `x, y` (canto superior esquerdo em px), `largura_max`, `altura_max`, `alinhamento_vertical: topo|centro`
   - `rotacao` (graus, padrão 0), `perspectiva` opcional (4 pontos destino) para peças em leve ângulo
   - `opacidade` (padrão 0.95), `intensidade_textura` (padrão 0.6)
   - Mapeamento de cores de variante para base (ex.: "branca-preta" → base "branca"; "branca-azul-escuro" → "branca"), com fallback configurável.
   - Valores iniciais razoáveis para imagem 1600x2000 (peito ~ centro horizontal, terço superior).
3. `calibrar.py`: para cada base, desenha a área de impressão (retângulo/polígono semitransparente) e salva em `calibracao/`. Se rodar com `--estampa caminho.png`, aplica essa estampa em todas as bases para conferir.
4. `aplicar.py` (principal):
   - Lê o CSV, agrupa por Handle, descobre tipo e todas as cores únicas de cada produto.
   - Para cada produto × cor × lado: encontra base e estampa, aplica e salva em `saida/{handle}/{handle}_{cor}_{lado}.png` (e uma versão `.jpg` qualidade 90, 1600px de altura, para web).
   - Argumentos: `--limite N`, `--handle X`, `--forcar` (refaz o que já existe; por padrão pula), `--workers N` (multiprocessamento).
   - Ao final, gera `saida/relatorio.csv` (handle, cor, lado, status: ok | sem_estampa | sem_base | erro, mensagem) e imprime um resumo.
   - Gera `saida/contato.jpg`: folha de contato com miniaturas de tudo para revisão rápida.
5. `compositor.py` com a função de aplicação realista:
   a. Recorta bordas transparentes da estampa (bounding box do alfa).
   b. Redimensiona mantendo proporção para caber em largura_max × altura_max (LANCZOS); aplica rotação/perspectiva se configurado.
   c. Textura do tecido: converte a região da base em escala de cinza, aplica high-pass (base − gaussian blur), e usa como mapa de deslocamento (cv2.remap, até ~4px proporcional à intensidade) para a estampa seguir as dobras.
   d. Luz e sombra: multiplica a estampa pela luminância normalizada da região da base (sombras das dobras escurecem a estampa; em peça escura use modo que não "apague" a estampa clara — combine multiply e screen conforme o brilho médio da base).
   e. Compõe com o alfa da estampa × opacidade, levemente suavizado nas bordas (blur 0.5px).
   f. Nunca alterar pixels fora da área da estampa.
6. `README.md` curto em português explicando como usar.
7. `tests/test_basico.py`: gera bases e estampas sintéticas, roda o pipeline e verifica arquivos de saída, tamanho e que pixels fora da área não mudaram. Rode os testes.

## Requisitos
- Código simples, comentado em português, sem dependências pesadas (sem IA, sem GPU).
- Funcionar em Windows e Mac. Caminhos com pathlib.
- Mensagens de erro claras (ex.: "Falta a base bases/hoodie_preta_frente.png usada por 12 produtos").
- Depois de criar, rode: instalar requirements, testes, `python calibrar.py`, e `python aplicar.py --limite 3` se houver bases/estampas reais na pasta. Mostre o resumo.

## Extra opcional (só se eu pedir depois)
- `subir_shopify.py`: enviar as imagens geradas para cada produto via Shopify Admin API (token em variável de ambiente SHOPIFY_TOKEN, loja em SHOPIFY_STORE), sem apagar as imagens atuais.
```

---

## Dicas para dar certo
- **Bases**: mesma resolução em todas (ex.: 1600x2000), peito e costas lisos e sem braço na frente.
- **Estampas**: PNG transparente em alta (mín. 2000px), sem fundo branco.
- Se a estampa parecer "colada": aumente `intensidade_textura` no `config.yaml`.
- Se estiver no lugar errado: ajuste `x`, `y`, `largura_max` e rode `python calibrar.py --estampa estampas/alguma.png`.
