/**
 * Kronus — cadastro facial feito no próprio totem.
 *
 * Um rosto cadastrado pela webcam do computador é reconhecido pela
 * câmera do tablet com folga bem menor: ótica, resolução e iluminação
 * diferentes produzem vetores em regiões diferentes. Cadastrar no mesmo
 * equipamento em que a pessoa bate o ponto elimina a diferença na
 * origem — mais barato do que compensá-la depois afrouxando o limiar,
 * que é o caminho que leva a reconhecer a pessoa errada.
 *
 * A entrada é escondida de propósito: três toques na logo. A tela fica
 * numa parede, e um botão "Manutenção" visível seria um convite
 * permanente a quem passa. E só existe quando o cliente ligou a opção e
 * definiu a senha — o servidor decide, não o quiosque.
 */
(function (global) {
  'use strict';

  //: Os três toques precisam caber nesta janela, contada do primeiro.
  //: Curta o bastante para não acontecer por acaso; longa o bastante
  //: para ser possível com luva ou em tela que responde devagar.
  var JANELA_TOQUES_MS = 1500;
  var TOQUES = 3;

  //: Faixa de luz aceitavel na imagem, em nivel medio (0 a 255).
  //:
  //: Abaixo do minimo o rosto vira sombra e o embedding sai pobre;
  //: acima do maximo estoura e some o contorno. O contraste separa a
  //: foto boa da foto lavada, que tem media certa e nenhuma informacao.
  var LUZ_MINIMA = 55;
  var LUZ_MAXIMA = 215;
  var CONTRASTE_MINIMO = 22;

  //: Quanto tempo insistir por luz melhor antes de fotografar assim
  //: mesmo.
  //:
  //: A luz de uma portaria e o que e. Depois de orientar e dar tempo de
  //: a pessoa se aproximar, insistir vira impasse — e um cadastro que
  //: nao acontece e pior do que um cadastro com luz mediana.
  //:
  //: Eram 5 s, e com cinco poses isso somava 25 s de espera no pior
  //: caso. 2,5 s dao tempo de a pessoa dar um passo, que e o que a
  //: orientacao pede.
  var ESPERA_POR_LUZ_MS = 2500;

  //: Leituras seguidas com tudo certo antes de disparar a foto.
  //:
  //: Tres, a 150 ms, sao quase meio segundo parado — mesma seguranca de
  //: antes, num laco mais rapido. Menos que isso dispararia no quadro em
  //: que a pessoa ainda esta se posicionando.
  var LEITURAS_PARA_DISPARAR = 3;

  //: Pausa depois de cada foto, para a pessoa mudar de pose.
  //: Sem ela, as cinco poses sairiam iguais em um segundo e meio.
  //:
  //: 1,2 s: o suficiente para virar o rosto, lendo a instrucao nova. O
  //: valor anterior, 2,2 s, somava onze segundos so de espera parada.
  var PAUSA_ENTRE_POSES_MS = 1200;

  //: Largura minima do rosto para o disparo automatico.
  //:
  //: Mais exigente que a do registro de ponto (0,32) de proposito. Perto
  //: da camera a luz e melhor — a propria tela ilumina o rosto — e sobra
  //: mais pixel para o recorte. Como a foto de cadastro e a referencia
  //: de todos os reconhecimentos futuros, vale pedir um passo a frente
  //: uma vez.
  //:
  //: Nao trava: passada a espera, o botao libera e a foto sai como
  //: estiver.
  var LARGURA_MINIMA_CADASTRO = 0.40;

  //: As mesmas poses do cadastro pelo painel. A variação entre elas é o
  //: que faz o reconhecimento aguentar a pessoa virar o rosto no dia a
  //: dia — sem isso, só o ângulo exato do cadastro é reconhecido.
  var POSES = [
    { angulo: 'frontal', instrucao: 'Olhe para a frente' },
    { angulo: 'esquerda', instrucao: 'Vire levemente para a sua esquerda' },
    { angulo: 'direita', instrucao: 'Vire levemente para a sua direita' },
    { angulo: 'cima', instrucao: 'Levante um pouco o queixo' },
    { angulo: 'baixo', instrucao: 'Abaixe um pouco o queixo' }
  ];

  var Manutencao = {
    config: null,
    chave: '',
    pessoas: [],
    pessoa: null,
    pose: 0,
    stream: null,
    ativa: false,
    pronto: false,
    _vigia: null,
    _capturando: false,
    _estaveis: 0,
    _prontoDesde: 0,
    _liberadoEm: 0,

    iniciar: function (config) {
      this.config = config;
      if (!config.disponivel) return;

      this._ligarGestoDeEntrada();
      this._ligarFormularios();
    },

    // ── Entrada ────────────────────────────────────────────────
    /**
     * Três toques na logo abrem a senha.
     *
     * Na logo, e não no relógio, por duas razões.
     *
     * A primeira: o relógio é o que a pessoa olha e toca. Ele aparece em
     * todas as telas, inclusive na de CPF, e quem espera a confirmação
     * fica batendo nele.
     *
     * A segunda pesa mais. Na tela ociosa **qualquer** toque já abre a
     * câmera — é assim que alguém registra o ponto quando o detector não
     * engatilha. Ou seja, tocar três vezes em qualquer lugar é o gesto
     * mais natural que existe ali, e o relógio caía bem no meio dele.
     * Uma pessoa impaciente chegaria à tela de senha sem procurar.
     *
     * A logo é a única região que não faz nada quando tocada. E o toque
     * nela para aqui: sem `stopPropagation`, o clique subiria para a
     * tela ociosa e abriria a câmera junto.
     */
    _ligarGestoDeEntrada: function () {
      var self = this;
      var toques = 0;
      var primeiro = 0;

      var alvos = document.querySelectorAll('[data-kronus-logo]');
      Array.prototype.forEach.call(alvos, function (alvo) {
        alvo.addEventListener('click', function (evento) {
          evento.stopPropagation();

          var agora = Date.now();
          if (agora - primeiro > JANELA_TOQUES_MS) {
            toques = 1;
            primeiro = agora;
            return;
          }
          toques += 1;
          if (toques >= TOQUES) {
            toques = 0;
            primeiro = 0;
            self.abrirSenha();
          }
        });
      });
    },

    abrirSenha: function () {
      this.ativa = true;
      this.config.aoEntrar();
      this._mostrar('tela-manut-senha');
      var campo = document.getElementById('campo-manut-senha');
      if (campo) { campo.value = ''; campo.focus(); }
      this._erro('erro-manut-senha', '');
    },

    sair: function () {
      this._fecharCamera();
      if (this.chave) {
        this._pedir('sair', 'POST', {}).catch(function () {});
      }
      this.chave = '';
      this.pessoa = null;
      this.ativa = false;
      // Esconder as telas da manutencao faz parte de sair. Sem isto elas
      // continuavam por cima do "Registre seu ponto": o totem voltava ao
      // ocioso por baixo, e a tela de senha ficava sobreposta, sem
      // caminho de volta.
      this._mostrar(null);
      this.config.aoSair();
    },

    // ── Requisições ────────────────────────────────────────────
    _pedir: function (rota, metodo, corpo) {
      var cabecalhos = { 'Authorization': 'Token ' + this.config.token };
      if (corpo) cabecalhos['Content-Type'] = 'application/json';
      if (this.chave) cabecalhos['X-Manutencao'] = this.chave;

      return fetch(this.config.urls[rota], {
        method: metodo,
        headers: cabecalhos,
        body: corpo ? JSON.stringify(corpo) : undefined,
        cache: 'no-store'
      }).then(function (resposta) {
        return resposta.json().then(function (dados) {
          dados._status = resposta.status;
          return dados;
        });
      });
    },

    _ligarFormularios: function () {
      var self = this;

      var form = document.getElementById('form-manut-senha');
      if (form) {
        form.addEventListener('submit', function (evento) {
          evento.preventDefault();
          self._entrar(document.getElementById('campo-manut-senha').value);
        });
      }

      Array.prototype.forEach.call(
        document.querySelectorAll('[data-manut-sair]'),
        function (botao) {
          botao.addEventListener('click', function () { self.sair(); });
        }
      );

      Array.prototype.forEach.call(
        document.querySelectorAll('[data-manut-voltar-lista]'),
        function (botao) {
          botao.addEventListener('click', function () {
            self._fecharCamera();
            self.pessoa = null;
            self._carregarLista();
          });
        }
      );

      var busca = document.getElementById('campo-manut-busca');
      if (busca) {
        busca.addEventListener('input', function () {
          self._desenharLista(busca.value);
        });
      }

      var aceite = document.getElementById('manut-lgpd-aceite');
      var continuar = document.getElementById('manut-lgpd-continuar');
      if (aceite && continuar) {
        aceite.addEventListener('change', function () {
          continuar.disabled = !aceite.checked;
        });
        continuar.addEventListener('click', function () {
          self._registrarConsentimento();
        });
      }

      var capturar = document.getElementById('manut-capturar');
      if (capturar) {
        capturar.addEventListener('click', function () { self._capturar(); });
      }

      var refazer = document.getElementById('manut-revisao-refazer');
      if (refazer) {
        refazer.addEventListener('click', function () {
          // Não é preciso apagar nada: o cadastro guarda as N mais
          // recentes, então as cinco novas empurram as antigas para
          // fora sozinhas.
          self._abrirCaptura();
        });
      }
      var manter = document.getElementById('manut-revisao-manter');
      if (manter) {
        manter.addEventListener('click', function () { self._carregarLista(); });
      }
    },

    _entrar: function (senha) {
      var self = this;
      this._erro('erro-manut-senha', '');
      this._pedir('entrar', 'POST', { senha: senha }).then(function (dados) {
        if (!dados.ok) {
          self._erro('erro-manut-senha', dados.mensagem || 'Senha incorreta.');
          return;
        }
        self.chave = dados.chave;
        self._carregarLista();
      }).catch(function () {
        self._erro('erro-manut-senha', 'Sem conexão com o servidor.');
      });
    },

    // ── Lista ──────────────────────────────────────────────────
    _carregarLista: function () {
      var self = this;
      this._pedir('colaboradores', 'GET', null).then(function (dados) {
        if (!dados.ok) return self._expirou(dados);
        self.pessoas = dados.colaboradores || [];
        var busca = document.getElementById('campo-manut-busca');
        if (busca) busca.value = '';
        self._desenharLista('');
        self._mostrar('tela-manut-lista');
      }).catch(function () {});
    },

    _desenharLista: function (filtro) {
      var lista = document.getElementById('manut-lista');
      var vazia = document.getElementById('manut-lista-vazia');
      if (!lista) return;

      var termo = (filtro || '').trim().toLowerCase();
      var visiveis = this.pessoas.filter(function (p) {
        return !termo || p.nome.toLowerCase().indexOf(termo) >= 0;
      });

      lista.innerHTML = '';
      var self = this;
      visiveis.forEach(function (pessoa) {
        var item = document.createElement('li');
        item.className = 'totem-manut-item';

        var nome = document.createElement('span');
        nome.className = 'totem-manut-item__nome';
        nome.textContent = pessoa.nome;

        var estado = document.createElement('span');
        estado.className = 'totem-manut-item__estado';
        estado.textContent = pessoa.amostras
          ? pessoa.amostras + ' amostra' + (pessoa.amostras > 1 ? 's' : '')
          : 'sem biometria';

        var botao = document.createElement('button');
        botao.type = 'button';
        botao.className = 'totem-manut-item__botao';
        botao.appendChild(nome);
        botao.appendChild(estado);
        botao.addEventListener('click', function () {
          self._escolher(pessoa);
        });

        item.appendChild(botao);
        lista.appendChild(item);
      });

      if (vazia) vazia.hidden = visiveis.length > 0;
    },

    _escolher: function (pessoa) {
      this.pessoa = pessoa;
      // Quem já consentiu não precisa consentir de novo: repetir o
      // pedido a cada recadastro transformaria o consentimento em
      // formalidade que se clica sem ler.
      if (pessoa.consentimento) return this._abrirCaptura();

      var nome = document.getElementById('manut-lgpd-nome');
      if (nome) nome.textContent = pessoa.nome;
      var aceite = document.getElementById('manut-lgpd-aceite');
      var continuar = document.getElementById('manut-lgpd-continuar');
      if (aceite) aceite.checked = false;
      if (continuar) continuar.disabled = true;
      this._erro('erro-manut-lgpd', '');
      this._mostrar('tela-manut-lgpd');
    },

    _registrarConsentimento: function () {
      var self = this;
      this._pedir('consentimento', 'POST', {
        colaborador_id: this.pessoa.id,
        aceite: true
      }).then(function (dados) {
        if (!dados.ok) {
          self._erro('erro-manut-lgpd', dados.mensagem || 'Não foi possível registrar.');
          return;
        }
        self.pessoa.consentimento = true;
        self._abrirCaptura();
      }).catch(function () {
        self._erro('erro-manut-lgpd', 'Sem conexão com o servidor.');
      });
    },

    // ── Captura ────────────────────────────────────────────────
    _abrirCaptura: function () {
      var self = this;
      this.pose = 0;
      this._capturando = false;
      this._estaveis = 0;
      this._prontoDesde = 0;
      this._liberadoEm = 0;
      this._erro('erro-manut-captura', '');
      var nome = document.getElementById('manut-captura-nome');
      if (nome) nome.textContent = this.pessoa.nome;
      this._atualizarPose();
      this._mostrar('tela-manut-captura');

      // Duas tentativas, como no registro de ponto: tablet de baixo
      // custo recusa `facingMode` ou a dica de resolução com
      // OverconstrainedError, e a segunda pede o mínimo.
      var abrir = function (restricoes) {
        return navigator.mediaDevices.getUserMedia(restricoes);
      };
      abrir({ video: { facingMode: 'user', width: 640, height: 480 }, audio: false })
        .catch(function (erro) {
          if (erro && (erro.name === 'OverconstrainedError'
                       || erro.name === 'ConstraintNotSatisfiedError')) {
            return abrir({ video: true, audio: false });
          }
          throw erro;
        })
        .then(function (stream) {
          self.stream = stream;
          var video = document.getElementById('manut-video');
          if (video) video.srcObject = stream;
          self._vigiarEnquadramento();
        })
        .catch(function (erro) {
          self._erro('erro-manut-captura',
            'Câmera indisponível' + (erro && erro.name ? ' (' + erro.name + ')' : '') + '.');
        });
    },

    _atualizarPose: function () {
      var pose = POSES[Math.min(this.pose, POSES.length - 1)];
      var passo = document.getElementById('manut-captura-passo');
      var instrucao = document.getElementById('manut-instrucao');
      if (passo) {
        passo.textContent = 'Pose ' + Math.min(this.pose + 1, POSES.length)
          + ' de ' + POSES.length;
      }
      if (instrucao) instrucao.textContent = pose.instrucao;

      var progresso = document.getElementById('manut-progresso');
      if (progresso) {
        progresso.innerHTML = '';
        for (var i = 0; i < POSES.length; i += 1) {
          var ponto = document.createElement('span');
          ponto.className = 'totem-manut-ponto'
            + (i < this.pose ? ' totem-manut-ponto--feito' : '')
            + (i === this.pose ? ' totem-manut-ponto--atual' : '');
          progresso.appendChild(ponto);
        }
      }
    },

    _capturar: function () {
      var self = this;
      var video = document.getElementById('manut-video');
      if (!video || video.readyState < 2) {
        this._erro('erro-manut-captura', 'A câmera ainda não está pronta.');
        return;
      }

      var canvas = document.createElement('canvas');
      canvas.width = 640;
      canvas.height = 480;
      canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);

      var botao = document.getElementById('manut-capturar');
      if (botao) botao.disabled = true;
      // Trava o disparo automatico enquanto a resposta nao volta: sem
      // isto o laco mandaria uma foto a cada 250 ms.
      this._capturando = true;
      this._erro('erro-manut-captura', '');

      this._pedir('amostra', 'POST', {
        colaborador_id: this.pessoa.id,
        imagem: canvas.toDataURL('image/jpeg', 0.9),
        angulo: POSES[Math.min(this.pose, POSES.length - 1)].angulo
      }).then(function (dados) {
        self._capturando = false;
        if (botao) botao.disabled = false;
        if (!dados.ok) {
          if (dados.codigo === 'sem_sessao') return self._expirou(dados);
          // Erro de enquadramento não avança a pose: repetir a mesma é
          // o que dá à pessoa a chance de corrigir o que foi apontado.
          // A pausa existe para ela ter esse tempo — sem ela, o disparo
          // automático repetiria o mesmo erro em rajada.
          self._erro('erro-manut-captura', dados.mensagem || 'Repita a captura.');
          self._estaveis = 0;
          self._prontoDesde = 0;
          self._liberadoEm = Date.now() + PAUSA_ENTRE_POSES_MS;
          if (global.KronusFaceDetector) global.KronusFaceDetector.reiniciar();
          return;
        }

        self.pose += 1;
        self.pessoa.amostras = dados.amostras;
        // Zera a contagem de leituras: sem isto o proximo quadro ja
        // nasceria "estavel" e a foto seguinte sairia na mesma pose.
        if (global.KronusFaceDetector) global.KronusFaceDetector.reiniciar();
        self._estaveis = 0;
        self._prontoDesde = 0;
        self._liberadoEm = Date.now() + PAUSA_ENTRE_POSES_MS;

        if (self.pose >= POSES.length) {
          // A avaliação do cadastro vem aqui, sobre o conjunto pronto —
          // e não a cada pose. Uma captura isolada pode ficar perto de
          // outra pessoa por acaso e não dizer nada sobre o cadastro.
          //
          // E é um convite, não um bloqueio: quem está na frente da
          // câmera decide entre refazer e seguir. Repetir à força seria
          // prender o operador num laço que ele não escolheu.
          if (dados.cadastro_fraco) {
            self._fecharCamera();
            self._perguntarSeRefaz(dados.aviso);
            return;
          }
          self._fecharCamera();
          self._carregarLista();
          return;
        }
        self._atualizarPose();
      }).catch(function () {
        self._capturando = false;
        if (botao) botao.disabled = false;
        self._erro('erro-manut-captura', 'Sem conexão com o servidor.');
      });
    },

    /**
     * Oferece refazer o cadastro que saiu pouco distinto.
     *
     * Duas saídas de verdade: refazer as cinco poses, ou manter o que
     * ficou. Manter é uma escolha legítima — o cadastro funciona, só vai
     * exigir o CPF com mais frequência —, e tirá-la deixaria alguém
     * preso repetindo poses até o sistema se dar por satisfeito.
     */
    _perguntarSeRefaz: function (aviso) {
      var self = this;
      var caixa = document.getElementById('tela-manut-revisao');
      if (!caixa) {
        self._carregarLista();
        return;
      }
      var texto = document.getElementById('manut-revisao-texto');
      if (texto) texto.textContent = aviso;
      this._mostrar('tela-manut-revisao');
    },

    /**
     * Só deixa capturar quando há rosto enquadrado.
     *
     * Sem isto, o operador apertava "Capturar" quando queria e o
     * servidor respondia que não viu rosto nenhum — erro frequente, e
     * inútil: quem está lá não tem como saber o que estava errado no
     * instante do clique.
     *
     * É o mesmo detector do registro de ponto, com o mesmo critério.
     * Assim a foto que entra no cadastro tem o enquadramento que o
     * reconhecimento vai exigir depois — cadastrar num enquadramento e
     * reconhecer em outro é parte do que fazia o totem falhar.
     */
    _vigiarEnquadramento: function () {
      var self = this;
      var detector = global.KronusFaceDetector;
      var video = document.getElementById('manut-video');
      var botao = document.getElementById('manut-capturar');
      var guia = document.querySelector('#tela-manut-captura .totem-camera__guia');
      if (!detector || !video || !botao) return;

      // Sem detector de verdade nao da para exigir enquadramento: seria
      // travar o botao para sempre. Ali o operador decide, como antes.
      if (detector.modo !== 'faceapi') {
        this.pronto = true;
        return;
      }

      var tela = document.createElement('canvas');
      tela.width = 320;
      tela.height = 240;
      var contexto = tela.getContext('2d');

      this._pararVigia();
      this.pronto = false;
      botao.disabled = true;

      // Valvula de escape.
      //
      // A conferencia de enquadramento e uma ajuda, nao uma tranca. Se
      // ela nao confirmar — camera diferente, luz dificil, um caso que
      // eu nao previ —, o botao libera assim mesmo depois de alguns
      // segundos. Um cadastro que nao pode ser feito e pior do que um
      // cadastro feito sem a conferencia.
      var desde = Date.now();
      var LIBERAR_APOS_MS = 5000;
      var liberado = false;

      this._vigia = setInterval(function () {
        if (!self.stream || video.readyState < 2) return;
        contexto.drawImage(video, 0, 0, tela.width, tela.height);

        var instrucao = document.getElementById('manut-instrucao');
        var detalhe = document.getElementById('manut-detalhe');

        detector.detectar(tela).then(function (r) {
          self.pronto = !!r.pronto;

          if (self.pronto) {
            liberado = false;
            botao.disabled = false;
            self._dispararQuandoPronto(contexto, tela, instrucao, r.proporcao);
          } else if (liberado || Date.now() - desde > LIBERAR_APOS_MS) {
            liberado = true;
            botao.disabled = false;
            if (instrucao) {
              instrucao.textContent =
                'Enquadramento não confirmado — capture assim mesmo se '
                + 'o rosto estiver visível.';
            }
          } else {
            botao.disabled = true;
            // Saiu do enquadramento: a contagem para o disparo recomeca,
            // senao a foto sairia no meio do movimento.
            self._estaveis = 0;
            self._prontoDesde = 0;
            if (instrucao) instrucao.textContent = detector.instrucaoPara(r.motivo);
          }

          // O numero medido, para quem estiver diagnosticando: sem ele,
          // "nao libera" e um sintoma sem causa.
          if (detalhe) {
            detalhe.textContent =
              'rosto ' + Math.round((r.proporcao || 0) * 100) + '% da largura'
              + ' · mínimo ' + Math.round(detector.LARGURA_MINIMA_ROSTO * 100) + '%'
              + ' · ' + (r.motivo || '—');
          }

          if (guia) {
            guia.classList.toggle('totem-camera__guia--pronto', r.pronto);
            guia.classList.toggle(
              'totem-camera__guia--ajustar', !r.pronto && r.presenca
            );
          }
        }).catch(function (erro) {
          // Falha do detector nao pode travar o cadastro, e nao pode
          // sumir: sem o aviso, "nao libera" fica sem explicacao.
          console.warn('[Kronus] deteccao no cadastro falhou:', erro);
          liberado = true;
          botao.disabled = false;
          if (detalhe) detalhe.textContent = 'detector indisponível';
        });
      }, 150);
    },

    /**
     * Dispara a foto sozinho quando tudo está no lugar.
     *
     * A pessoa que está sendo cadastrada não tem como apertar o botão —
     * ela está posicionando o rosto. Quem apertava era o operador, do
     * lado, olhando de viés para a tela: o pior ângulo possível para
     * julgar enquadramento.
     *
     * A luz é preferência, não condição. Insiste por alguns segundos e
     * orienta; passado esse tempo, fotografa assim mesmo — a luz de uma
     * portaria é o que é, e um cadastro que não acontece é pior do que
     * um cadastro com luz mediana.
     */
    _dispararQuandoPronto: function (contexto, tela, instrucao, proporcao) {
      var agora = Date.now();

      // Enviando, ou ainda na pausa entre poses.
      if (this._capturando || agora < (this._liberadoEm || 0)) {
        if (instrucao) instrucao.textContent = 'Pronto — mude para a próxima pose';
        return;
      }

      if (!this._prontoDesde) this._prontoDesde = agora;

      var esperando = agora - this._prontoDesde < ESPERA_POR_LUZ_MS;

      // Perto primeiro: a luz melhora sozinha quando a pessoa se
      // aproxima, porque a tela do totem ilumina o rosto. Pedir o passo
      // a frente resolve os dois problemas de uma vez, e e mais rapido
      // do que esperar a luz do ambiente mudar.
      if (proporcao && proporcao < LARGURA_MINIMA_CADASTRO && esperando) {
        this._estaveis = 0;
        if (instrucao) {
          instrucao.textContent = 'Chegue mais perto da câmera';
        }
        return;
      }

      var luz = this._medirLuz(contexto, tela);

      if (!luz.boa && esperando) {
        this._estaveis = 0;
        if (instrucao) {
          instrucao.textContent =
            luz.media !== null && luz.media < LUZ_MINIMA
              ? 'Pouca luz no rosto — aproxime-se ou procure um lugar mais claro'
              : 'Ajuste a luz — evite claridade forte atrás de você';
        }
        return;
      }

      this._estaveis = (this._estaveis || 0) + 1;
      if (instrucao) {
        instrucao.textContent = luz.boa
          ? 'Segure assim…'
          : 'Luz não é a ideal — vou registrar assim mesmo';
      }

      if (this._estaveis >= LEITURAS_PARA_DISPARAR) {
        this._estaveis = 0;
        this._prontoDesde = 0;
        this._capturar();
      }
    },

    /**
     * Nível de luz e contraste do quadro.
     *
     * Amostra um pixel a cada 16 para caber no orçamento de 250 ms de
     * um tablet modesto — a média de um rosto não muda por olhar
     * dezesseis vezes menos pontos.
     */
    _medirLuz: function (contexto, tela) {
      var dados;
      try {
        dados = contexto.getImageData(0, 0, tela.width, tela.height).data;
      } catch (e) {
        // Canvas "sujo" por origem cruzada não deixa ler os pixels.
        // Sem medida, seguimos como se a luz estivesse boa: a foto vale
        // mais do que a aferição.
        return { boa: true, media: null, contraste: null };
      }

      var soma = 0, soma2 = 0, n = 0;
      for (var i = 0; i < dados.length; i += 4 * 16) {
        var y = 0.299 * dados[i] + 0.587 * dados[i + 1] + 0.114 * dados[i + 2];
        soma += y;
        soma2 += y * y;
        n += 1;
      }
      if (!n) return { boa: true, media: null, contraste: null };

      var media = soma / n;
      var contraste = Math.sqrt(Math.max(soma2 / n - media * media, 0));
      return {
        boa: media >= LUZ_MINIMA && media <= LUZ_MAXIMA
             && contraste >= CONTRASTE_MINIMO,
        media: media,
        contraste: contraste
      };
    },

    _pararVigia: function () {
      if (this._vigia) {
        clearInterval(this._vigia);
        this._vigia = null;
      }
    },

    _fecharCamera: function () {
      this._pararVigia();
      if (this.stream) {
        this.stream.getTracks().forEach(function (t) { t.stop(); });
        this.stream = null;
      }
      var video = document.getElementById('manut-video');
      if (video) video.srcObject = null;
    },

    // ── Auxiliares ─────────────────────────────────────────────
    _expirou: function (dados) {
      this.chave = '';
      this._fecharCamera();
      this.abrirSenha();
      this._erro('erro-manut-senha', dados.mensagem || 'Sessão expirada.');
    },

    _mostrar: function (id) {
      ['tela-manut-senha', 'tela-manut-lista', 'tela-manut-lgpd',
       'tela-manut-captura', 'tela-manut-revisao'].forEach(function (tela) {
        var el = document.getElementById(tela);
        if (el) el.hidden = tela !== id;
      });
    },

    _erro: function (id, texto) {
      var el = document.getElementById(id);
      if (!el) return;
      el.textContent = texto || '';
      el.hidden = !texto;
    }
  };

  global.KronusManutencao = Manutencao;
})(window);
