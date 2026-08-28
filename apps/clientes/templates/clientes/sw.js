/**
 * Kronus — Service Worker do app do colaborador e do administrador.
 *
 * Diferente do Service Worker do totem, este **nunca** guarda resposta
 * de API. Num app de ponto, servir uma marcação do cache é pior do que
 * dizer "sem conexão": a pessoa acredita que bateu o ponto e não bateu.
 *
 * O que ele faz é manter o app abrindo offline — a casca, o CSS e a
 * página que explica a falta de conexão — para que o ícone na tela
 * inicial não abra um erro do navegador.
 */
'use strict';

var VERSAO = 'kronus-app-{{ versao_estaticos|default:"v1" }}';
// URLs com carimbo de versao: sem ele o fetch aqui dentro bate no
// cache HTTP do navegador (que o Nginx marcou como `immutable`) e o
// Service Worker acabaria guardando justamente o arquivo velho que
// estamos tentando substituir.
var ESSENCIAIS = [
  '/static/css/main.css?v={{ versao_estaticos|default:"dev" }}',
  '/static/img/favicon.svg'
];

self.addEventListener('install', function (evento) {
  evento.waitUntil(
    caches.open(VERSAO)
      .then(function (cache) { return cache.addAll(ESSENCIAIS); })
      // Um asset que falhou não pode impedir a instalação: o app
      // funcionaria mesmo assim, e travar aqui deixaria o usuário sem
      // Service Worker nenhum.
      .catch(function (erro) { console.warn('[Kronus] cache parcial:', erro); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (evento) {
  evento.waitUntil(
    caches.keys().then(function (chaves) {
      return Promise.all(chaves.map(function (chave) {
        if (chave !== VERSAO) return caches.delete(chave);
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (evento) {
  var url = new URL(evento.request.url);

  // Nunca da rede para o cache: registrar ponto, consultar saldo e
  // qualquer POST passam direto. Uma resposta cacheada aqui seria uma
  // mentira sobre o estado do ponto.
  var somenteRede =
    evento.request.method !== 'GET'
    || url.pathname.startsWith('/api/')
    || url.pathname.startsWith('/ponto/')
    || url.pathname.startsWith('/accounts/');

  if (somenteRede) return;

  // Estáticos: cache primeiro, com atualização em segundo plano.
  if (url.pathname.startsWith('/static/')) {
    evento.respondWith(
      caches.match(evento.request).then(function (guardado) {
        var daRede = fetch(evento.request).then(function (resposta) {
          if (resposta && resposta.ok) {
            var copia = resposta.clone();
            caches.open(VERSAO).then(function (c) { c.put(evento.request, copia); });
          }
          return resposta;
        }).catch(function () { return guardado; });
        return guardado || daRede;
      })
    );
    return;
  }

  // Navegação: rede primeiro, cache como rede de segurança.
  if (evento.request.mode === 'navigate') {
    evento.respondWith(
      fetch(evento.request).catch(function () {
        return caches.match(evento.request)
          || caches.match('/static/css/main.css');
      })
    );
  }
});
