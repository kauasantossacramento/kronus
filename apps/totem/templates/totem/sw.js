{% load kronus_tags %}/**
 * Kronus — Service Worker do totem (Seção 6.5.3 do plano).
 *
 * Estratégia:
 *   · assets estáticos → cache-first (o totem precisa abrir sem rede)
 *   · chamadas de API  → network-only (uma batida cacheada seria fraude)
 *   · navegação        → network-first com fallback para a página offline
 *
 * O ponto crítico é o segundo: **nunca** servir resposta cacheada de
 * `/api/v1/totem/`. Um "sucesso" vindo do cache faria o colaborador
 * acreditar que bateu o ponto quando nada foi gravado.
 */
const VERSAO = 'kronus-totem-{{ versao_estaticos|default:"v1" }}';
const CACHE_ESTATICO = VERSAO + '-estatico';

// Com o carimbo de versao, e nao sem ele.
//
// A pagina pede `totem-app.js?v=abc`; a lista guardava
// `totem-app.js` puro, e `caches.match` compara a URL inteira. Nenhuma
// das duas se encontrava: o pre-cache existia e nunca era usado, e so o
// cache de runtime — que so enche depois da primeira visita com rede —
// segurava o totem offline.
const ASSETS = [
  '/totem/offline/',
  '{% estatico "totem/css/totem.css" %}',
  '{% estatico "totem/js/totem-app.js" %}',
  '{% estatico "totem/js/face-detector.js" %}',
  '{% estatico "totem/js/camera-manager.js" %}',
  '{% estatico "totem/js/offline-handler.js" %}',
  '{% estatico "totem/js/ui-controller.js" %}',
  '{% estatico "totem/js/fila-offline.js" %}',
  '{% estatico "totem/js/personalizacao.js" %}',
  // A biblioteca de deteccao facial. Ficava de fora porque vinha de um
  // CDN — e o comentario ao lado dela na pagina dizia que o Service
  // Worker a cacheava, o que nunca foi verdade: resposta de outro host
  // e opaca. Offline, o totem ficava sem detector nenhum.
  '{% estatico "totem/js/vendor/face-api.min.js" %}',
  '{% estatico "img/logo-kronus-branco.svg" %}',
  '{% estatico "img/ks-tec-logo.png" %}',
  '{% estatico "img/favicon.svg" %}'
];

/** Modelos do face-api.js — grandes; cacheados sem bloquear a instalação. */
const MODELOS = [
  '{% estatico "totem/js/models/tiny_face_detector_model-weights_manifest.json" %}',
  '{% estatico "totem/js/models/tiny_face_detector_model-shard1" %}'
];

self.addEventListener('install', function (evento) {
  evento.waitUntil(
    caches.open(CACHE_ESTATICO).then(function (cache) {
      // `addAll` falha inteiro se um item falhar; cacheamos um a um para
      // que a ausência de um modelo não impeça o totem de instalar.
      return Promise.all(
        ASSETS.concat(MODELOS).map(function (url) {
          return cache.add(url).catch(function () {
            console.warn('[Kronus SW] não foi possível cachear', url);
          });
        })
      );
    }).then(function () {
      return self.skipWaiting();
    })
  );
});

self.addEventListener('activate', function (evento) {
  evento.waitUntil(
    caches.keys().then(function (chaves) {
      return Promise.all(
        chaves
          .filter(function (chave) { return chave.indexOf(VERSAO) !== 0; })
          .map(function (chave) { return caches.delete(chave); })
      );
    }).then(function () {
      return self.clients.claim();
    })
  );
});

self.addEventListener('fetch', function (evento) {
  const requisicao = evento.request;
  const url = new URL(requisicao.url);

  if (requisicao.method !== 'GET') return;
  if (url.origin !== self.location.origin) return;

  // API: nunca do cache. Registro de ponto exige o servidor.
  if (url.pathname.startsWith('/api/')) {
    return;
  }

  // Navegação: rede primeiro, página offline como último recurso.
  if (requisicao.mode === 'navigate') {
    evento.respondWith(
      fetch(requisicao).catch(function () {
        return caches.match('/totem/offline/');
      })
    );
    return;
  }

  // Estáticos: cache primeiro, com revalidação em segundo plano.
  evento.respondWith(
    caches.match(requisicao).then(function (cacheada) {
      const daRede = fetch(requisicao)
        .then(function (resposta) {
          if (resposta && resposta.status === 200) {
            const copia = resposta.clone();
            caches.open(CACHE_ESTATICO).then(function (cache) {
              cache.put(requisicao, copia);
            });
          }
          return resposta;
        })
        .catch(function () {
          return cacheada;
        });

      return cacheada || daRede;
    })
  );
});
