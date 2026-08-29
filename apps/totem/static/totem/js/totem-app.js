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
    pausado: false,

    // ── Constantes de desempenho (Seção 6.5.2) ────────────────
    // Um quadro a cada 3 s deixava a pessoa parada na frente do totem
    // esperando ate 3 s pela primeira analise — e ate 6 s quando a
    // camera ainda precisava reabrir. Era o que fazia parecer que o
    // totem so respondia ao toque. A 700 ms a analise ocupa por volta de
    // um sexto do tempo num tablet modesto.
    INTERVALO_IDLE_MS: 700,      // ~1,4 analises por segundo no ocioso
    INTERVALO_ATIVO_MS: 150,     // ~6,7 FPS com a câmera ativa
    // 2 s entre envios eram sentidos como travamento quando o primeiro
    // quadro nao passava: a pessoa ficava parada esperando sem sinal de
    // que algo acontecia. 1,2 s ainda protege o servidor de uma rajada.
    DEBOUNCE_ENVIO_MS: 1200,     // mínimo entre envios ao servidor
    TIMEOUT_CAMERA_MS: 20000,    // sem match em 20 s → fallback
    TIMEOUT_FALLBACK_MS: 30000,  // sem interação em 30 s → idle
    QUALIDADE_JPEG: 0.7,

    // ══════════════════════════════════════════════════════════
    // Inicialização
    // ══════════════════════════════════════════════════════════
    iniciar: function (config) {
      var self0 = this;
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
          motivoDegradado: function () { return self0.degradado; },
          aoPedirRecarga: this.recarregarQuandoOcioso.bind(this),
          // Configuracao se aplica ao vivo; codigo novo exige recarga.
          aoPedirRecargaTotal: this.recarregarQuandoLivre.bind(this),
          versaoEstaticos: config.versaoEstaticos
        })
        .iniciar();

      var self = this;
      this.detector.carregar(config.urls.modelos).then(function (modo) {
        console.info('[Kronus] Detector em modo:', modo);
        // Degradar em silencio foi o pior do defeito anterior: o totem
        // parecia inteiro, ninguem era reconhecido e nao havia sinal
        // algum de que o reconhecimento tinha morrido. Agora avisa na
        // tela e conta ao servidor, para o suporte ver sem estar la.
        if (modo !== 'faceapi') self._avisarDegradado();
        self.irParaIdle();
      });

      // O Service Worker avisa quando ha versao nova. Responder pelo
      // canal e o que diz a ele "esta pagina sabe se atualizar" — sem
      // resposta, ele navega a forca, que e o certo para uma pagina
      // antiga demais para ouvir.
      if (global.navigator && global.navigator.serviceWorker) {
        global.navigator.serviceWorker.addEventListener('message', function (evento) {
          var dados = evento.data || {};
          if (dados.tipo !== 'kronus-atualizado') return;
          if (evento.ports && evento.ports[0]) {
            evento.ports[0].postMessage({ tratado: true });
          }
          self.recarregarQuandoLivre();
        });
      }

      // Libera a câmera ao fechar a aba/app.
      global.addEventListener('pagehide', function () {
        self.camera.fechar();
        self.offline.parar();
      });
    },

    /**
     * Diz, na tela e ao servidor, que o reconhecimento facial caiu.
     *
     * Sem detector de rosto o totem continua registrando ponto por CPF —
     * entao ele nao para. Mas o operador precisa saber, ou vai passar o
     * dia mandando as pessoas repetirem o rosto para uma camera que
     * nunca vai enviar nada.
     */
    _avisarDegradado: function () {
      var motivo = this.detector.motivoDegradado || 'detector indisponivel';

      var faixa = document.getElementById('totem-degradado');
      if (faixa) {
        faixa.hidden = false;
        var onde = faixa.querySelector('[data-motivo]');
        if (onde) onde.textContent = motivo;
      }

      // Vai junto do heartbeat: o servidor anota uma vez e so volta a
      // anotar depois de uma hora. Um heartbeat imediato porque esperar
      // ate 30s para contar que o reconhecimento morreu e tempo em que
      // o suporte olha o painel e ve um totem saudavel.
      this.degradado = motivo;
      if (this.offline && this.offline.enviarHeartbeat) {
        this.offline.enviarHeartbeat();
      }
    },

    /**
     * Suspende o reconhecimento e solta a câmera.
     *
     * Usado pelo modo de manutenção, que precisa da mesma câmera para
     * cadastrar. Duas partes pedindo o mesmo dispositivo deixariam as
     * duas sem imagem — em tablet de baixo custo há uma câmera só, e
     * ela não é compartilhável.
     */
    pausar: function () {
      this.pausado = true;
      this._pararLoop();
      this.camera.fechar();

      // Cancelar o que ja estava agendado, e nao so parar o laco.
      //
      // Sem isto, um `agendar(irParaFallback)` disparado antes da pausa
      // trazia a tela de CPF de volta por cima da manutencao — e quem
      // estava cadastrando digitava ali achando que fazia parte do
      // fluxo, batendo o proprio ponto sem querer.
      this.ui.limparTimers();
      if (this._timeoutFallback) {
        clearTimeout(this._timeoutFallback);
        this._timeoutFallback = null;
      }
      // Uma resposta em voo tambem nao pode virar tela de sucesso.
      this.enviando = false;
      this.ultimoEnvio = Date.now();

      var telas = this.config.elementos.telas;
      Object.keys(telas).forEach(function (nome) {
        if (telas[nome]) telas[nome].hidden = true;
      });
    },

    retomar: function () {
      this.pausado = false;
      this.irParaIdle();
    },

    /**
     * Recarrega quando ninguém estiver usando.
     *
     * O deploy troca os arquivos no servidor e não alcança uma tela já
     * aberta — e um totem de parede fica dias com a mesma página. A
     * recarga é o único jeito de o código novo chegar; o cuidado é
     * escolher a hora.
     *
     * Espera o estado ocioso: ali não há ninguém na frente da câmera,
     * ninguém digitando CPF, e a manutenção não está aberta. A tela
     * cheia cai na recarga — o navegador não deixa reentrar sem gesto —
     * mas o primeiro toque a devolve, e num totem esse toque acontece
     * em segundos.
     */
    recarregarQuandoLivre: function () {
      var self = this;
      if (this._recargaDeVersao) return;
      this._recargaDeVersao = true;
      console.info('[Kronus] Versão nova disponível — recarrego ao ficar ocioso.');

      var tentar = function () {
        var livre = (self.estado === 'idle' || self.estado === 'offline')
          && !self.pausado
          && !self.enviando;

        // Fila offline pendente nao impede: ela vive no localStorage e
        // sobrevive a recarga. Ja provado em ferramentas/prova_offline.py.
        if (livre) {
          global.location.reload();
          return;
        }
        setTimeout(tentar, 4000);
      };
      setTimeout(tentar, 4000);
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
      if (this.pausado) return;
      this.estado = 'idle';
      this.enviando = false;
      this.tentativasFalhas = 0;
      // A camera fica aberta.
      //
      // Fechar aqui nao poupava nada: o proximo tique do laco a reabria
      // em seguida. O que se ganhava era so a espera da reabertura —
      // segundos, num tablet modesto — bem no instante em que alguem
      // chega para bater o ponto. Quem fecha de verdade e o `pagehide`,
      // ao sair da pagina.
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
        if (self.pausado) return;
        if (!self.camera.ativa) {
          // Analisa assim que a camera abrir, e nao so no tique
          // seguinte: perder um ciclo inteiro aqui era metade da demora
          // que se sentia ao chegar na frente do totem.
          self.camera.abrir().then(executar).catch(function (erro) {
            console.warn('[Kronus]', self.camera.descreverErro(erro));
          });
          return;
        }
        var canvas = self.camera.frameParaDeteccao();
        if (!canvas) return;

        // No ocioso basta reconhecer que ha alguem ali; o rigor fica
        // para o instante de enviar ao servidor, que nao muda.
        self.detector.detectar(canvas, self.estado === 'idle').then(function (resultado) {
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
            // A moldura vira o retorno: amarela enquanto falta ajustar,
            // e nada e enviado ao servidor ate ela fechar em verde.
            self.ui.enquadramento(
              resultado.presenca ? 'ajustar' : null
            );
            return;
          }

          self.ui.enquadramento('pronto');

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
          self._recargaPendente = false;
          self.atualizarConfiguracao();
          return;
        }
        setTimeout(tentar, 3000);
      };
      tentar();
    },

    /**
     * Busca a configuração e aplica **sem recarregar a página**.
     *
     * Recarregar era o caminho simples, e tinha um efeito colateral que
     * só aparece no equipamento: a tela cheia cai. O navegador não deixa
     * reentrar sem gesto do usuário, então o totem ficava com barra de
     * endereço até alguém tocar na tela — e barra de navegador convida o
     * colaborador a sair da página.
     *
     * Aplicar ao vivo cobre o que muda na prática: logo, cores, imagens
     * da tela ociosa, mensagens e tamanhos. Mudança de estrutura da
     * página continua exigindo recarga, mas essa vem com o deploy, não
     * com um clique do administrador.
     */
    atualizarConfiguracao: function () {
      var self = this;
      if (!this.config || !this.config.urls || !this.config.urls.config) return;

      fetch(this.config.urls.config, {
        headers: { 'Authorization': 'Token ' + this.config.token }
      })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (dados) {
          if (!dados || !dados.empresa) return;
          self.config.empresa = dados.empresa;
          if (global.KronusPersonalizacao) {
            global.KronusPersonalizacao.aplicar(
              dados.empresa, self.config.elementos
            );
          }
          if (dados.totem) {
            self.config.permiteFallback = dados.totem.permite_fallback_cpf;
            if (dados.empresa.tentativas_antes_do_cpf !== undefined) {
              self.config.tentativasReconhecimento =
                dados.empresa.tentativas_antes_do_cpf;
            }
          }
          console.info('[Kronus] configuração atualizada sem recarregar.');
        })
        .catch(function (erro) {
          console.warn('[Kronus] não foi possível atualizar a configuração:', erro);
        });
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
      if (this.pausado) return;
      var self = this;
      this.estado = 'camera';
      // Zera a contagem de leituras herdada do ocioso: la o criterio e
      // mais frouxo, e aproveita-la aqui autorizaria um envio sem a
      // estabilidade que o envio exige.
      this.detector.reiniciar();
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
      // A manutencao usa a mesma camera e o mesmo servidor: um quadro
      // enviado dali gravaria ponto de quem esta cadastrando.
      if (this.pausado) return;
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

          // O servidor pede um segundo quadro antes de gravar. A
          // resposta vem com `ok: true` porque nada falhou — mas
          // `identificado: false`, e tratar isso como sucesso mostraria
          // a tela de confirmacao de um ponto que ainda nao existe.
          if (dados.codigo === 'confirmando') {
            self.ui.definirInstrucao('Confirmando… fique parado', true);
            return;
          }

          if (dados.ok && dados.identificado !== false) {
            self.irParaSucesso(dados);
          } else if (dados.codigo === 'discordancia'
                     || dados.codigo === 'ambiguo') {
            // O sistema esta dizendo que nao sabe. Pedir para repetir e
            // melhor do que escolher um nome — e o laco ja continua
            // enviando, entao basta orientar sem sair da camera.
            self.ui.definirInstrucao(dados.mensagem, false);
            self.detector.reiniciar();
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
      if (this.pausado) return;
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
      if (this.pausado) return;
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
