/**
 * Kronus — aplicação do totem.
 *
 * Máquina de estados da Seção 6.5.1 do plano:
 *
 *   IDLE ──(rosto detectado)──▶ CAMERA ──(match)──▶ SUCESSO ──(5s)──▶ IDLE
 *                                 │
 *                                 └──(sem match)──▶ FALLBACK ──▶ SUCESSO
 *
 *   Qualquer estado ──(2 heartbeats falhos)──▶ OFFLINE ──▶ reload
 *
 * Restrições do alvo (Positivo Tab 7 Vision, 3 GB — Seção 6.5.2):
 *   · detecção a 1 frame/3 s no ocioso, 5 FPS com a câmera ativa
 *   · canvas de detecção em 320x240, envio em 640x480 JPEG q=0.7
 *   · debounce de 2 s entre envios ao servidor
 *   · vanilla JS, sem framework
 */
(function (global) {
  'use strict';

  var TotemApp = {
    config: null,
    estado: 'idle',
    enviando: false,
    ultimoEnvio: 0,
    loopDeteccao: null,

    // ── Constantes de desempenho (Seção 6.5.2) ────────────────
    INTERVALO_IDLE_MS: 3000,     // 1 frame a cada 3 s no ocioso
    INTERVALO_ATIVO_MS: 200,     // 5 FPS com a câmera ativa
    DEBOUNCE_ENVIO_MS: 2000,     // mínimo entre envios ao servidor
    TIMEOUT_CAMERA_MS: 20000,    // sem match em 20 s → fallback
    TIMEOUT_FALLBACK_MS: 30000,  // sem interação em 30 s → idle
    QUALIDADE_JPEG: 0.7,

    // ══════════════════════════════════════════════════════════
    // Inicialização
    // ══════════════════════════════════════════════════════════
    iniciar: function (config) {
      this.config = config;
      this.ui = global.KronusUI.inicializar(config.elementos);
      this.personalizacao = global.KronusPersonalizacao;
      // Identidade visual da empresa aplicada antes de tudo: cor, logo e
      // slides sao a primeira coisa que o colaborador ve.
      this.personalizacao.aplicar(config.empresa, config.elementos);
      this.camera = global.KronusCamera;
      this.detector = global.KronusFaceDetector;
      this.offline = global.KronusOffline;

      this.camera.inicializar(config.elementos.video);
      this._ligarEventos();

      // Relógio antes de tudo: a tela ociosa já precisa mostrar a hora.
      this.ui.atualizarRelogios();
      setInterval(this.ui.atualizarRelogios.bind(this.ui), 1000);

      this.offline
        .configurar({
          urlHeartbeat: config.urls.heartbeat,
          token: config.token,
          versao: config.versao,
          aoFicarOffline: this.aoFicarOffline.bind(this),
          aoVoltarOnline: this.aoVoltarOnline.bind(this),
          aoSincronizar: this.ui.sincronizarRelogio.bind(this.ui),
          aoPedirRecarga: this.recarregarQuandoOcioso.bind(this)
        })
        .iniciar();

      var self = this;
      this.detector.carregar(config.urls.modelos).then(function (modo) {
        console.info('[Kronus] Detector em modo:', modo);
        self.irParaIdle();
      });

      // Libera a câmera ao fechar a aba/app.
      global.addEventListener('pagehide', function () {
        self.camera.fechar();
        self.offline.parar();
      });
    },

    _ligarEventos: function () {
      var self = this;
      var el = this.config.elementos;

      // Toque na tela ociosa entra direto na câmera — útil quando o
      // detector não engatilha (contraluz, boné).
      if (el.telas.idle) {
        el.telas.idle.addEventListener('click', function () {
          if (self.estado === 'idle') self.irParaCamera();
        });
      }

      if (el.botaoFallback) {
        el.botaoFallback.addEventListener('click', function () {
          self.irParaFallback();
        });
      }
      if (el.erroFallbackBotao) {
        el.erroFallbackBotao.addEventListener('click', function () {
          self.irParaFallback();
        });
      }
      if (el.botaoVoltar) {
        el.botaoVoltar.addEventListener('click', function () {
          self.irParaIdle();
        });
      }
      if (el.erroVoltarBotao) {
        el.erroVoltarBotao.addEventListener('click', function () {
          self.irParaIdle();
        });
      }

      var campos = el.fallback || {};
      if (campos.cpf) {
        campos.cpf.addEventListener('input', function (evento) {
          evento.target.value = self.ui.mascararCPF(evento.target.value);
          self._reiniciarTimeoutFallback();
        });
      }
      if (campos.nascimento) {
        campos.nascimento.addEventListener('input', function (evento) {
          evento.target.value = self.ui.mascararData(evento.target.value);
          self._reiniciarTimeoutFallback();
        });
      }
      if (campos.formulario) {
        campos.formulario.addEventListener('submit', function (evento) {
          evento.preventDefault();
          self.enviarFallback();
        });
      }
    },

    // ══════════════════════════════════════════════════════════
    // Estado 1 — ocioso
    // ══════════════════════════════════════════════════════════
    irParaIdle: function () {
      this.estado = 'idle';
      this.enviando = false;
      this.tentativasFalhas = 0;
      this.camera.fechar();
      this.detector.reiniciar();
      this.ui.mostrar('idle');
      this._iniciarLoop(this.INTERVALO_IDLE_MS);
    },

    /**
     * No ocioso a detecção usa a própria câmera em baixa cadência.
     * Abrir a câmera só quando alguém aparece seria ideal, mas não há
     * sensor de presença — então detectamos com o mínimo de frames
     * possível (1 a cada 3 s) para poupar bateria.
     */
    _iniciarLoop: function (intervalo) {
      var self = this;
      this._pararLoop();

      var executar = function () {
        if (!self.camera.ativa) {
          self.camera.abrir().catch(function (erro) {
            console.warn('[Kronus]', self.camera.descreverErro(erro));
          });
          return;
        }
        var canvas = self.camera.frameParaDeteccao();
        if (!canvas) return;

        self.detector.detectar(canvas).then(function (resultado) {
          // `presenca` acorda a tela; `pronto` autoriza o envio. Sao
          // decisoes diferentes de proposito: no ocioso basta alguem
          // se aproximar, mas gastar uma chamada de reconhecimento
          // exige rosto enquadrado e estavel.
          if (self.estado === 'idle') {
            if (resultado.presenca) self.irParaCamera();
            return;
          }

          if (self.estado !== 'camera') return;

          if (!resultado.pronto) {
            self.ui.definirInstrucao(
              self.detector.instrucaoPara(resultado.motivo), false
            );
            return;
          }

          self.ui.definirInstrucao('Identificando…', true);
          // Zera a contagem: sem isso o proximo frame do mesmo rosto
          // ja estaria "estavel" e dispararia um segundo envio antes
          // da resposta do primeiro.
          self.detector.reiniciar();
          self.enviarFrame();
        });
      };

      this.loopDeteccao = setInterval(executar, intervalo);
      executar();
    },

    /**
     * Recarrega o quiosque, mas so com a tela ociosa.
     *
     * Recarregar durante um reconhecimento perderia a batida de quem
     * esta na frente da camera. A batida e a obrigacao legal; a logo
     * nova pode esperar o proximo intervalo entre pessoas.
     */
    recarregarQuandoOcioso: function () {
      var self = this;
      this._recargaPendente = true;

      var tentar = function () {
        if (!self._recargaPendente) return;
        if (self.estado === 'idle' || self.estado === 'offline') {
          window.location.reload();
          return;
        }
        setTimeout(tentar, 3000);
      };
      tentar();
    },

    _pararLoop: function () {
      if (this.loopDeteccao) {
        clearInterval(this.loopDeteccao);
        this.loopDeteccao = null;
      }
    },

    // ══════════════════════════════════════════════════════════
    // Estado 2 — câmera ativa
    // ══════════════════════════════════════════════════════════
    irParaCamera: function () {
      var self = this;
      this.estado = 'camera';
      this.ui.mostrar('camera');
      this.ui.definirInstrucao('Posicione o rosto no centro', false);

      this.camera
        .abrir()
        .then(function () {
          self._iniciarLoop(self.INTERVALO_ATIVO_MS);
          // Sem identificação em 20 s, oferecemos o CPF em vez de deixar
          // a pessoa tentando indefinidamente.
          self.ui.agendar(function () {
            if (self.estado === 'camera') {
              if (self.config.permiteFallback) {
                self.irParaFallback();
              } else {
                self.irParaIdle();
              }
            }
          }, self.TIMEOUT_CAMERA_MS);
        })
        .catch(function (erro) {
          self.ui.mostrarErro(
            self.camera.descreverErro(erro),
            self.config.permiteFallback
          );
        });
    },

    enviarFrame: function () {
      var agora = Date.now();
      if (this.enviando || agora - this.ultimoEnvio < this.DEBOUNCE_ENVIO_MS) return;

      var imagem = this.camera.capturarJPEG(this.QUALIDADE_JPEG);
      if (!imagem) return;

      this.enviando = true;
      this.ultimoEnvio = agora;
      var self = this;

      fetch(this.config.urls.recognize, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Token ' + this.config.token
        },
        body: JSON.stringify({ image: imagem, totem_id: this.config.identificador })
      })
        .then(function (resposta) { return resposta.json(); })
        .then(function (dados) {
          self.enviando = false;
          if (dados.ok) {
            self.irParaSucesso(dados);
          } else if (dados.codigo === 'intervalo_minimo') {
            // Batida duplicada: avisa e volta ao ocioso, sem insistir.
            self.ui.mostrarErro(dados.mensagem, false);
            self.ui.agendar(self.irParaIdle.bind(self), 4000);
          } else if (dados.codigo === 'nao_identificado') {
            // Contar as tentativas e oferecer o CPF no momento certo:
            // antes, o totem insistia até o tempo da câmera esgotar, e a
            // pessoa ficava parada sem saber se devia esperar ou
            // desistir. A segunda chance evita mandar para a digitação
            // quem só estava mal enquadrado na primeira foto.
            self.tentativasFalhas = (self.tentativasFalhas || 0) + 1;
            var limite = self.config.tentativasReconhecimento || 0;

            if (limite && self.tentativasFalhas >= limite
                && self.config.permiteFallback) {
              self.ui.definirInstrucao('Não reconhecemos seu rosto.', false);
              self.ui.agendar(self.irParaFallback.bind(self), 900);
            } else if (self.tentativasFalhas === 1) {
              self.ui.definirInstrucao('Não reconhecido. Olhe para a câmera.', false);
            } else {
              self.ui.definirInstrucao('Continue tentando...', false);
            }
          } else if (dados.codigo === 'sem_rosto') {
            self.ui.definirInstrucao('Aproxime-se da câmera', false);
          } else if (dados.codigo === 'multiplos_rostos') {
            self.ui.definirInstrucao('Apenas uma pessoa por vez', false);
          } else {
            self.ui.mostrarErro(dados.mensagem, self.config.permiteFallback);
          }
        })
        .catch(function () {
          self.enviando = false;
          // Falha de rede aqui não muda de estado: o heartbeat é quem
          // decide se o equipamento está offline.
        });
    },

    // ══════════════════════════════════════════════════════════
    // Estado 3 — sucesso
    // ══════════════════════════════════════════════════════════
    irParaSucesso: function (dados) {
      this.estado = 'sucesso';
      this._pararLoop();
      this.camera.fechar();

      this.ui.preencherSucesso(dados);
      this.ui.mostrar('sucesso');

      var segundos = dados.segundos_exibicao || this.config.segundosSucesso || 5;
      var self = this;
      var restante = segundos;

      this.ui.atualizarContagem(restante);
      var contagem = setInterval(function () {
        restante -= 1;
        self.ui.atualizarContagem(Math.max(restante, 0));
        if (restante <= 0) {
          clearInterval(contagem);
          self.irParaIdle();
        }
      }, 1000);
      this.ui._timers.push(contagem);
    },

    // ══════════════════════════════════════════════════════════
    // Estado 4 — fallback por CPF
    // ══════════════════════════════════════════════════════════
    irParaFallback: function () {
      // Zera aqui e no retorno ao ocioso: sem isso, a proxima pessoa na
      // fila herdaria as falhas da anterior e cairia direto na digitacao.
      this.tentativasFalhas = 0;
      if (!this.config.permiteFallback) return this.irParaIdle();

      this.estado = 'fallback';
      this._pararLoop();
      this.camera.fechar();
      this.ui.limparFallback();
      this.ui.mostrar('fallback');
      this.ui.focarFallback();
      this._reiniciarTimeoutFallback();
    },

    _reiniciarTimeoutFallback: function () {
      var self = this;
      if (this._timeoutFallback) clearTimeout(this._timeoutFallback);
      this._timeoutFallback = setTimeout(function () {
        if (self.estado === 'fallback') self.irParaIdle();
      }, this.TIMEOUT_FALLBACK_MS);
    },

    enviarFallback: function () {
      var campos = this.config.elementos.fallback;
      var cpf = (campos.cpf.value || '').replace(/\D/g, '');
      var nascimento = (campos.nascimento.value || '').replace(/\D/g, '');

      if (cpf.length !== 11) {
        return this.ui.erroFallback('Informe os 11 dígitos do CPF.');
      }
      if (nascimento.length !== 8) {
        return this.ui.erroFallback('Informe a data de nascimento (DD/MM/AAAA).');
      }

      this.ui.erroFallback('');
      var self = this;

      fetch(this.config.urls.punchCpf, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Token ' + this.config.token
        },
        body: JSON.stringify({
          cpf: cpf,
          // O backend aceita DDMMAAAA; enviamos assim para não depender
          // do parser de data do WebView do Android.
          data_nascimento: nascimento,
          totem_id: this.config.identificador
        })
      })
        .then(function (resposta) { return resposta.json(); })
        .then(function (dados) {
          if (dados.ok) {
            self.irParaSucesso(dados);
          } else {
            self.ui.erroFallback(dados.mensagem || 'Não foi possível registrar.');
            self._reiniciarTimeoutFallback();
          }
        })
        .catch(function () {
          self.ui.erroFallback('Sem conexão com o servidor. Tente novamente.');
        });
    },

    // ══════════════════════════════════════════════════════════
    // Estado 5 — offline
    // ══════════════════════════════════════════════════════════
    aoFicarOffline: function () {
      if (this.estado === 'offline') return;
      this.estado = 'offline';
      this._pararLoop();
      this.camera.fechar();
      this.ui.mostrar('offline');

      var self = this;
      var segundos = this.config.segundosOffline || 120;
      this.offline.iniciarCountdown(
        segundos,
        function (restante, total) { self.ui.atualizarOffline(restante, total); },
        function (voltou) {
          if (voltou) self.irParaIdle();
          else global.location.reload();
        }
      );
    },

    aoVoltarOnline: function () {
      if (this.estado === 'offline') this.irParaIdle();
    }
  };

  global.KronusTotem = TotemApp;
})(window);
