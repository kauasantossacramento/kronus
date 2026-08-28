# Modelos do face-api.js

Pesos do **TinyFaceDetector**, usados pelo totem para detectar a
presença de um rosto no próprio tablet. O reconhecimento — dizer *quem*
é a pessoa — acontece no servidor, com ArcFace.

## Arquivos presentes

| Arquivo | Tamanho | Uso |
|---|---|---|
| `tiny_face_detector_model-weights_manifest.json` | 3 KB | obrigatório |
| `tiny_face_detector_model-shard1` | 189 KB | obrigatório |
| `face_landmark_68_tiny_model-weights_manifest.json` | 4 KB | alinhamento |
| `face_landmark_68_tiny_model-shard1` | 75 KB | alinhamento |

Origem: <https://github.com/justadudewhohacks/face-api.js/tree/master/weights>

## Por que agora são versionados

A primeira versão deste arquivo argumentava o contrário — que 270 KB de
binário não valiam o espaço no histórico. Estava errado, e o custo
apareceu em produção: **sem os pesos, o totem cai no detector
heurístico**, que decide se há alguém na frente da câmera pela variação
de luminância. Uma mão passando, uma sombra ou alguém andando atrás
disparavam o reconhecimento; como não havia rosto, a tela pedia CPF.

270 KB versionados uma vez valem menos do que um totem que dispara
sozinho. Os arquivos mudam raramente e a alternativa — baixar no
deploy — acrescenta uma dependência de rede a cada implantação.

## Os de landmark

`face_landmark_68_tiny` é usado para conferir **alinhamento**: rosto
muito girado ou inclinado produz um recorte ruim, e um recorte ruim
gera embedding ruim. Rejeitar antes de enviar economiza uma viagem ao
servidor e evita um "não reconheci" que na verdade era enquadramento.

## Se os arquivos sumirem

`face-detector.js` continua caindo no detector heurístico e registra no
console:

    [Kronus] Falha ao carregar os modelos — deteccao heuristica ativada.

O totem funciona, mas em modo degradado. O diagnóstico
(`/totem/<token>/diagnostico/`) mostra qual detector está ativo.
