/**
 * Kronus — detecção de conectividade do totem (Estado 5, Seção 6.5.1).
 *
 * `navigator.onLine` sozinho não basta: ele reporta "online" quando o
 * Wi-Fi está conectado mas sem rota para a internet — cenário comum em
 * rede corporativa com portal cativo ou switch caído. Por isso o
 * heartbeat é a fonte de verdade: **duas falhas consecutivas** marcam o
 * equipamento como offline.
 */
(function (global) {
  'use strict';

  var OfflineHandler = {
    online: true,
    falhasConsecutivas: 0,
    intervaloHeartbeat: null,

    /** Duas falhas seguidas = offline (Seção 6.5.1). */
    FALHAS_PARA_OFFLINE: 2,

    /** Heartbeat a cada 30 segundos, conforme o plano. */
    INTERVALO_MS: 30000,

    configurar: function (opcoes) {
      this.urlHeartbeat = opcoes.urlHeartbeat;
      this.token = opcoes.token;
      this.versao = opcoes.versao || '1.0.0';
      this.aoFicarOffline = opcoes.aoFicarOffline || function () {};
      this.aoVoltarOnline = opcoes.aoVoltarOnline || function () {};
      this.aoSincronizar = opcoes.aoSincronizar || function () {};
      this.motivoDegradado = opcoes.motivoDegradado || function () { return ''; };
      this.aoPedirRecargaTotal = opcoes.aoPedirRecargaTotal || function () {};
      this._versaoEstaticos = opcoes.versaoEstaticos || undefined;
      return this;
    },

    iniciar: function () {
      var self = this;

      // Os eventos do navegador antecipam a mudança; o heartbeat confirma.
      global.addEventListener('offline', function () {
        self._marcarOffline('evento do navegador');
      });
      global.addEventListener('online', function () {
        self.enviarHeartbeat();
      });

      this.enviarHeartbeat();
      this.intervaloHeartbeat = setInterval(function () {
        self.enviarHeartbeat();
      }, this.INTERVALO_MS);
    },

    _modoDeExibicao: function () {
      try {
        if (global.matchMedia('(display-mode: fullscreen)').matches) {
          return 'fullscreen';
        }
        if (global.matchMedia('(display-mode: standalone)').matches
            || global.navigator.standalone === true) {
          return 'standalone';
        }
      } catch (e) {}
      return 'browser';
    },

    parar: function () {
      if (this.intervaloHeartbeat) {
        clearInterval(this.intervaloHeartbeat);
        this.intervaloHeartbeat = null;
      }
    },

    enviarHeartbeat: function () {
      var self = this;
      var carga = { versao: this.versao };

      // Se o reconhecimento facial caiu, o heartbeat leva o motivo: e o
      // unico canal que ja existe e que o suporte le do painel.
      var motivo = this.motivoDegradado && this.motivoDegradado();
      if (motivo) carga.degradado = String(motivo).slice(0, 200);

      // Como a pagina esta aberta. Instalado como aplicativo, a recarga
      // nao perde a tela cheia e a atualizacao entra sozinha; numa aba,
      // alguem vai precisar tocar no equipamento. Quem opera precisa
      // saber disso sem ir ate la.
      carga.modo_exibicao = this._modoDeExibicao();

      if (navigator.getBattery) {
        // A bateria alimenta o painel do Master; falha aqui é irrelevante.
        navigator.getBattery().then(function (bateria) {
          carga.bateria = Math.round(bateria.level * 100);
        }).catch(function () {});
      }

      return fetch(this.urlHeartbeat, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Token ' + this.token
        },
        body: JSON.stringify(carga),
        // Nunca usar cache no heartbeat: uma resposta cacheada faria o
        // totem se achar online com a rede caída.
        cache: 'no-store'
      })
        .then(function (resposta) {
          if (!resposta.ok) throw new Error('HTTP ' + resposta.status);
          return resposta.json();
        })
        .then(function (dados) {
          self.falhasConsecutivas = 0;
          if (!self.online) {
            self.online = true;
            self.aoVoltarOnline(dados);
          }
          if (dados && dados.servidor) {
            self.aoSincronizar(dados.servidor);
          }
          self._verificarConfiguracao(dados);
          return dados;
        })
        .catch(function (erro) {
          self.falhasConsecutivas += 1;
          if (self.falhasConsecutivas >= self.FALHAS_PARA_OFFLINE) {
            self._marcarOffline(erro.message);
          }
          return null;
        });
    },

    /**
     * Recarrega o quiosque quando a configuracao muda no painel.
     *
     * A alternativa seria alguem ir ate cada tablet depois de trocar a
     * logo ou a cor. Comparamos um inteiro em vez de diferenciar a
     * configuracao inteira: e barato e funciona mesmo depois de o totem
     * passar horas offline.
     *
     * A recarga so acontece com a tela **ociosa**. Recarregar no meio de
     * um reconhecimento perderia a batida de quem esta na frente da
     * camera — e a batida vale mais do que a logo nova aparecer agora.
     */
    _verificarConfiguracao: function (dados) {
      var config = dados && dados.config;
      if (!config) return;

      // Duas coisas diferentes chegam por aqui.
      //
      // A configuracao (cores, logo, mensagens) se aplica ao vivo, sem
      // recarregar — recarregar derrubaria a tela cheia por nada.
      //
      // O carimbo dos estaticos e outra historia: ele muda quando ha
      // codigo novo no servidor, e codigo novo so entra recarregando.
      // Sem esta comparacao, um totem instalado ficava preso na versao
      // com que foi aberto ate alguem ir ate la — que era exatamente o
      // que acontecia.
      // Recarga pedida pelo suporte: mesmo caminho do codigo novo,
      // com a mesma cortesia de esperar a tela ficar ociosa.
      var pedido = String(config.recarga_total_em || '');
      if (pedido) {
        if (this._recargaPedida === undefined) {
          this._recargaPedida = pedido;
        } else if (pedido !== this._recargaPedida) {
          this._recargaPedida = pedido;
          console.info('[Kronus] Recarga pedida pelo suporte.');
          this.aoPedirRecargaTotal();
        }
      }

      var estaticos = String(config.estaticos || '');
      if (estaticos) {
        if (this._versaoEstaticos === undefined) {
          this._versaoEstaticos = estaticos;
        } else if (estaticos !== this._versaoEstaticos) {
          this._versaoEstaticos = estaticos;
          console.info('[Kronus] Codigo novo no servidor — recarrego ao ficar ocioso.');
          this.aoPedirRecargaTotal();
        }
      }

      var assinatura = String(config.versao) + '|' + String(config.recarregar_em || '');
      if (this._assinaturaConfig === undefined) {
        this._assinaturaConfig = assinatura;
        return;
      }
      if (assinatura === this._assinaturaConfig) return;

      this._assinaturaConfig = assinatura;
      console.info('[Kronus] Configuracao alterada — aplicando ao vivo.');
      this.aoPedirRecarga();
    },

    /**
     * Substituido pelo app: so ele sabe se a tela esta ociosa.
     *
     * O padrao nao faz nada de proposito. Recarregar aqui derrubaria a
     * tela cheia — e sem o app em cima, nem daria para saber se ha
     * alguem na frente da camera no momento.
     */
    aoPedirRecarga: function () {
      console.warn('[Kronus] pedido de recarga sem tratador.');
    },

    _marcarOffline: function (motivo) {
      if (!this.online) return;
      this.online = false;
      console.warn('[Kronus] Totem offline:', motivo);
      this.aoFicarOffline(motivo);
    },

    /**
     * Countdown da tela offline.
     *
     * Ao fim, recarrega a página — o reload limpa qualquer estado
     * corrompido do app, o que é mais confiável do que tentar
     * ressuscitar a máquina de estados no lugar.
     */
    iniciarCountdown: function (segundos, aoAtualizar, aoTerminar) {
      var restante = segundos;
      var self = this;

      aoAtualizar(restante, segundos);
      var intervalo = setInterval(function () {
        restante -= 1;
        aoAtualizar(Math.max(restante, 0), segundos);

        // Se a conexão voltar antes do fim, não há por que esperar.
        if (self.online) {
          clearInterval(intervalo);
          aoTerminar(true);
          return;
        }
        if (restante <= 0) {
          clearInterval(intervalo);
          aoTerminar(false);
        }
      }, 1000);

      return function cancelar() {
        clearInterval(intervalo);
      };
    }
  };

  global.KronusOffline = OfflineHandler;
})(window);
