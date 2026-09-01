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

//: O carimbo cru, para a pagina comparar com o dela.
//:
//: Sem ele o aviso dizia apenas "ha versao nova", e uma pagina que
//: tinha acabado de carregar COM essa versao se recarregava a toa. A
//: ativacao do Service Worker significa "ha codigo novo publicado", e
//: nao "a pagina aberta esta velha".
const CARIMBO = '{{ versao_estaticos|default:"v1" }}';
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
    }).then(avisarOuRecarregar)
  );
});

/**
 * Leva o codigo novo ate uma tela que ja esta aberta.
 *
 * Um totem de parede fica com a mesma pagina carregada por dias. O
 * deploy troca os arquivos no servidor e nao alcanca quem ja esta
 * rodando — e, num equipamento instalado longe, ninguem vai la recarregar.
 *
 * Duas etapas, porque as duas geracoes de pagina convivem:
 *
 *   1. Avisa. A pagina nova entende o recado e recarrega **quando
 *      estiver ociosa**, sem interromper quem esta batendo o ponto.
 *   2. Se ninguem responder em alguns segundos, e porque a pagina
 *      aberta e antiga e nao sabe ouvir. Ai navegamos nos: e brusco,
 *      mas deixar um totem preso numa versao com defeito e pior.
 */
function avisarOuRecarregar() {
  return self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    .then(function (janelas) {
      return Promise.all(janelas.map(function (janela) {
        if (janela.url.indexOf('/totem/') === -1) return null;
        return new Promise(function (resolver) {
          var respondeu = false;

          // Avisa mais de uma vez antes de desistir.
          //
          // O Service Worker ativa enquanto a pagina ainda carrega, e um
          // aviso enviado antes de ela registrar o ouvinte se perde — a
          // pagina nova era tratada como antiga e recarregada a toa.
          // Repetir cobre essa janela sem custo: quem ja respondeu nao
          // recebe de novo.
          var avisar = function () {
            if (respondeu) return;
            var canal = new MessageChannel();
            canal.port1.onmessage = function () {
              respondeu = true;
              resolver(null);
            };
            try {
              janela.postMessage(
                { tipo: 'kronus-atualizado', carimbo: CARIMBO },
                [canal.port2]
              );
            } catch (e) {
              // Nem postMessage passou: so resta navegar.
            }
          };

          avisar();
          setTimeout(avisar, 2500);
          setTimeout(avisar, 5000);

          setTimeout(function () {
            if (respondeu) return resolver(null);
            if (janela.navigate) {
              janela.navigate(janela.url).catch(function () {}).then(resolver);
            } else {
              resolver(null);
            }
          }, 9000);
        });
      }));
    });
}

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
  //
  // A biblioteca de detecção e os modelos ignoram a query string.
  //
  // Eles são artefatos de terceiros, com versão própria, presos ao
  // arquivo: não mudam porque o Kronus mudou. Mas a página os pede com
  // `?v=<versão dos estáticos>`, e `caches.match` compara a URL
  // inteira — então **todo deploy invalidava 1,3 MB de biblioteca**.
  //
  // O efeito era o totem baixar tudo de novo pela rede do local. Onde
  // ela é fraca isso passa do tempo que o detector espera, e o totem
  // entra em modo degradado dizendo "face-api.js não carregou" — foi
  // exatamente o que aconteceu depois de uma atualização, com o
  // reconhecimento parando num equipamento que estava funcionando.
  //
  // Ignorando a query, a cópia guardada responde na hora e a nova
  // desce em segundo plano. Se algum dia a biblioteca for trocada, o
  // arquivo novo entra no cache no primeiro carregamento e passa a
  // valer no seguinte — uma volta de atraso numa dependência que muda
  // uma vez por ano, contra o totem cego depois de cada deploy.
  const pesadoEImutavel = /\/(vendor\/face-api\.min\.js|js\/models\/)/.test(url.pathname);
  const opcoesBusca = pesadoEImutavel ? { ignoreSearch: true } : undefined;

  evento.respondWith(
    caches.match(requisicao, opcoesBusca).then(function (cacheada) {
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
