/**
 * Kronus — fila de marcações do totem sem conexão.
 *
 * Anexo IX, requisitos 4 e 5: a marcação deve vir de coletor on-line,
 * podendo **excepcionalmente** estar off-line — e, nesse caso, ser
 * enviada assim que a conexão voltar.
 *
 * A promessa que este módulo faz é forte: **a batida feita sem conexão
 * chega ao servidor quando a conexão voltar**. Um modo offline que perde
 * marcação é pior do que não ter modo offline, porque a pessoa acredita
 * que bateu o ponto e a empresa fica sem o registro.
 *
 * Por isso três regras:
 *
 *   1. A marcação é gravada **antes** de qualquer tentativa de envio.
 *      Gravar depois perderia a batida se o aparelho desligasse no meio.
 *
 *   2. Nada sai da fila sem confirmação do servidor. Recusa fica na fila
 *      marcada, para o operador ver — apagar em silêncio uma batida
 *      recusada perde o registro de trabalho de alguém.
 *
 *   3. Cada marcação carrega um identificador próprio. Se a resposta se
 *      perder na volta, o reenvio não duplica.
 */
(function (global) {
  'use strict';

  var CHAVE_FILA = 'kronus-fila-offline';
  var CHAVE_CACHE = 'kronus-colaboradores-offline';
  var CHAVE_CACHE_EM = 'kronus-colaboradores-offline-em';
  var CHAVE_SAL = 'kronus-offline-sal';
  var CHAVE_ITERACOES = 'kronus-offline-iteracoes';

  //: Idade máxima do cache de colaboradores. Passado disso, quem foi
  //: admitido depois não conseguiria bater o ponto offline.
  var VALIDADE_CACHE_MS = 36 * 60 * 60 * 1000;

  var FilaOffline = {
    urlSincronizar: '',
    urlColaboradores: '',
    token: '',
    aoMudar: function () {},

    configurar: function (opcoes) {
      this.urlSincronizar = opcoes.urlSincronizar;
      this.urlColaboradores = opcoes.urlColaboradores;
      this.token = opcoes.token;
      this.aoMudar = opcoes.aoMudar || function () {};
      return this;
    },

    // ── Armazenamento ────────────────────────────────────────
    _ler: function (chave, padrao) {
      try {
        var bruto = localStorage.getItem(chave);
        return bruto ? JSON.parse(bruto) : padrao;
      } catch (e) {
        return padrao;
      }
    },

    _gravar: function (chave, valor) {
      try {
        localStorage.setItem(chave, JSON.stringify(valor));
        return true;
      } catch (e) {
        // Sem espaço ou armazenamento bloqueado. Devolver `false` deixa
        // quem chamou decidir — e quem chama recusa a batida em vez de
        // fingir que gravou.
        console.error('[Kronus] não foi possível gravar a fila:', e);
        return false;
      }
    },

    fila: function () {
      return this._ler(CHAVE_FILA, []);
    },

    pendentes: function () {
      return this.fila().filter(function (m) { return !m.recusada; });
    },

    recusadas: function () {
      return this.fila().filter(function (m) { return m.recusada; });
    },

    // ── Registrar uma marcação ───────────────────────────────
    registrar: function (colaboradorId, tipo) {
      var marcacao = {
        uuid: this._identificador(),
        colaborador_id: colaboradorId,
        tipo: tipo || null,
        // Hora do aparelho: é a única disponível sem conexão. O servidor
        // guarda esta como hora da marcação e a da chegada como hora da
        // gravação — o AFD tem os dois campos justamente por isso.
        momento: new Date().toISOString(),
        criada_em: Date.now()
      };

      var fila = this.fila();
      fila.push(marcacao);
      if (!this._gravar(CHAVE_FILA, fila)) return null;

      this.aoMudar(this.pendentes().length);
      return marcacao;
    },

    _identificador: function () {
      if (global.crypto && global.crypto.randomUUID) {
        return global.crypto.randomUUID();
      }
      // Reserva para navegador antigo — o caso do tablet de baixo custo,
      // que é justamente onde o modo offline mais importa.
      var aleatorio = function () {
        return Math.floor((1 + Math.random()) * 0x10000).toString(16).slice(1);
      };
      return [aleatorio() + aleatorio(), aleatorio(), aleatorio(),
              aleatorio(), aleatorio() + aleatorio() + aleatorio()].join('-');
    },

    // ── Envio ────────────────────────────────────────────────
    sincronizar: function () {
      var self = this;
      var pendentes = this.pendentes();
      if (!pendentes.length || !this.urlSincronizar) {
        return Promise.resolve({ enviadas: 0 });
      }

      var lote = pendentes.slice(0, 200).map(function (m) {
        return {
          uuid: m.uuid,
          colaborador_id: m.colaborador_id,
          tipo: m.tipo,
          momento: m.momento
        };
      });

      return fetch(this.urlSincronizar, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Token ' + this.token
        },
        body: JSON.stringify({ marcacoes: lote })
      })
        .then(function (resposta) {
          if (!resposta.ok) throw new Error('HTTP ' + resposta.status);
          return resposta.json();
        })
        .then(function (dados) {
          return self._aplicarResultados(dados.resultados || {});
        })
        .catch(function (erro) {
          // Falha de rede: a fila fica intacta e tenta de novo depois.
          // Este é o caminho normal quando a conexão ainda não voltou.
          console.warn('[Kronus] sincronização adiada:', erro);
          return { enviadas: 0, erro: true };
        });
    },

    _aplicarResultados: function (resultados) {
      var enviadas = 0;
      var recusadas = 0;

      var fila = this.fila().map(function (marcacao) {
        var resultado = resultados[marcacao.uuid];
        if (!resultado) return marcacao;

        if (resultado.situacao === 'aceita' || resultado.situacao === 'duplicada') {
          enviadas += 1;
          marcacao.enviada = true;
          return marcacao;
        }
        // Recusada fica na fila, marcada. Some da contagem de pendentes
        // mas continua visível — apagar perderia o registro de que
        // alguém tentou bater o ponto.
        recusadas += 1;
        marcacao.recusada = true;
        marcacao.motivo = resultado.motivo || 'Recusada pelo servidor.';
        return marcacao;
      }).filter(function (marcacao) {
        return !marcacao.enviada;
      });

      this._gravar(CHAVE_FILA, fila);
      this.aoMudar(this.pendentes().length);
      return { enviadas: enviadas, recusadas: recusadas };
    },

    // ── Cache de colaboradores ───────────────────────────────
    atualizarColaboradores: function () {
      var self = this;
      if (!this.urlColaboradores) return Promise.resolve(false);

      return fetch(this.urlColaboradores, {
        headers: { 'Authorization': 'Token ' + this.token }
      })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (dados) {
          if (!dados || !dados.colaboradores) return false;
          self._gravar(CHAVE_CACHE, dados.colaboradores);
          self._gravar(CHAVE_SAL, dados.sal || '');
          self._gravar(CHAVE_ITERACOES, dados.iteracoes || 0);
          self._gravar(CHAVE_CACHE_EM, Date.now());
          return true;
        })
        .catch(function () { return false; });
    },

    colaboradores: function () {
      return this._ler(CHAVE_CACHE, []);
    },

    cacheValido: function () {
      var em = this._ler(CHAVE_CACHE_EM, 0);
      return em && (Date.now() - em) < VALIDADE_CACHE_MS;
    },

    /**
     * Encontra quem digitou CPF e data de nascimento, sem conexão.
     *
     * A lista guardada **não** tem CPF em claro — ela fica num tablet de
     * portaria, que é compartilhado e roubável. O que ela tem é um
     * resumo criptográfico, calculado pelo servidor; aqui só comparamos.
     */
    identificar: function (cpf, nascimento) {
      return this._resumo(cpf, nascimento).then(function (resumo) {
        var achado = null;
        FilaOffline.colaboradores().forEach(function (c) {
          if (c.identificacao === resumo) achado = c;
        });
        return achado;
      });
    },

    /**
     * Refaz a mesma derivação que o servidor usou ao montar a lista.
     *
     * PBKDF2 com muitas iterações: conferir uma digitação custa **uma**
     * derivação — um piscar de olhos. Varrer o espaço de CPFs custaria
     * isso vezes um bilhão, que é o que torna inútil roubar o tablet
     * para extrair a base de documentos da empresa.
     */
    _resumo: function (cpf, nascimento) {
      if (!global.crypto || !global.crypto.subtle) {
        return Promise.resolve(null);
      }
      var sal = this._ler(CHAVE_SAL, '');
      var iteracoes = this._ler(CHAVE_ITERACOES, 0);
      if (!sal || !iteracoes) return Promise.resolve(null);

      var digitos = String(cpf || '').replace(/\D/g, '');
      var entrada = new TextEncoder().encode(digitos + '|' + (nascimento || ''));

      return global.crypto.subtle
        .importKey('raw', entrada, { name: 'PBKDF2' }, false, ['deriveBits'])
        .then(function (chave) {
          return global.crypto.subtle.deriveBits({
            name: 'PBKDF2',
            salt: new TextEncoder().encode(sal),
            iterations: iteracoes,
            hash: 'SHA-256'
          }, chave, 256);
        })
        .then(function (buffer) {
          return Array.prototype.map.call(new Uint8Array(buffer), function (b) {
            return ('0' + b.toString(16)).slice(-2);
          }).join('');
        })
        .catch(function (erro) {
          console.error('[Kronus] falha ao conferir identificação:', erro);
          return null;
        });
    }
  };

  global.KronusFilaOffline = FilaOffline;
})(window);
