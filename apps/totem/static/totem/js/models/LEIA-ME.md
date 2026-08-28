# Modelos do face-api.js

Esta pasta hospeda os pesos do **TinyFaceDetector**, usados pelo totem
para detectar a presença de um rosto no próprio tablet (Seção 2.3 do
plano). O reconhecimento — dizer *quem* é a pessoa — acontece no
servidor, com ArcFace.

## Arquivos esperados

| Arquivo | Tamanho aprox. |
|---|---|
| `tiny_face_detector_model-weights_manifest.json` | 1 KB |
| `tiny_face_detector_model-shard1` | 190 KB |
| `face_landmark_68_tiny_model-weights_manifest.json` | 1 KB |
| `face_landmark_68_tiny_model-shard1` | 80 KB |

Os dois primeiros são obrigatórios; os de landmark são opcionais e só
entram se for adicionada checagem de alinhamento no client-side.

## Como obter

Baixe de um dos repositórios do face-api.js:

- https://github.com/justadudewhohacks/face-api.js/tree/master/weights
- https://github.com/vladmandic/face-api/tree/master/model (fork mantido)

Copie os arquivos para esta pasta e rode `python manage.py collectstatic`.

## Por que não versionamos os pesos

São binários de algumas centenas de KB que mudam a cada release do
face-api.js. Mantê-los no repositório inflaria o histórico do Git sem
ganho — o `LEIA-ME` e o fallback abaixo resolvem melhor.

## Sem os modelos, o totem ainda funciona

`face-detector.js` cai automaticamente para um **detector heurístico**
(variação de luminância na região central) e registra no console:

    [Kronus] Falha ao carregar os modelos — detecção heurística ativada.

Nesse modo o disparo da captura é menos preciso, mas a identificação
continua correta: quem decide é o servidor. O totem nunca deixa de
funcionar por ausência dos pesos.
