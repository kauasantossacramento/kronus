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
      this._erro('erro-manut-captura', '');

      this._pedir('amostra', 'POST', {
        colaborador_id: this.pessoa.id,
        imagem: canvas.toDataURL('image/jpeg', 0.9),
        angulo: POSES[Math.min(this.pose, POSES.length - 1)].angulo
      }).then(function (dados) {
        if (botao) botao.disabled = false;
        if (!dados.ok) {
          if (dados.codigo === 'sem_sessao') return self._expirou(dados);
          // Erro de enquadramento não avança a pose: repetir a mesma é
          // o que dá à pessoa a chance de corrigir o que foi apontado.
          self._erro('erro-manut-captura', dados.mensagem || 'Repita a captura.');
          return;
        }

        self.pose += 1;
        self.pessoa.amostras = dados.amostras;

        if (self.pose >= POSES.length) {
          self._fecharCamera();
          // Um cadastro fraco precisa ser dito aqui, com a pessoa ainda
          // na frente da câmera. Descobrir semanas depois, pelo
          // colaborador que nunca é reconhecido, é tarde.
          if (dados.cadastro_fraco) {
            self._erro('erro-manut-captura', dados.aviso);
            self.pose = 0;
            self._atualizarPose();
            return;
          }
          self._carregarLista();
          return;
        }
        self._atualizarPose();
      }).catch(function () {
        if (botao) botao.disabled = false;
        self._erro('erro-manut-captura', 'Sem conexão com o servidor.');
      });
    },

    _fecharCamera: function () {
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
       'tela-manut-captura'].forEach(function (tela) {
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
