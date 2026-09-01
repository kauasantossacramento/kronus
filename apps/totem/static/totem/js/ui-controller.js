/**
 * Kronus — controle visual dos estados do totem (Seção 6.5.1).
 *
 * Este módulo só mexe no DOM. A decisão de *quando* mudar de estado é do
 * `totem-app.js` — separar as duas coisas evita que a lógica de negócio
 * fique presa a nomes de classe CSS.
 *
 * Estados: idle · camera · sucesso · fallback · offline · erro
 */
(function (global) {
  'use strict';

  //: Emojis da comemoracao, montados por code point.
  //:
  //: Escritos assim, e nao colados direto, porque este arquivo passa
  //: por copia entre maquinas com codificacoes diferentes — e um emoji
  //: corrompido vira caixinha na tela do cliente.
  var EMOJI_FESTA = String.fromCodePoint(0x1F389);          // 🎉
  var SIMBOLOS_FESTA = [
    String.fromCodePoint(0x1F44F),                          // 👏
    String.fromCodePoint(0x1F389),                          // 🎉
    String.fromCodePoint(0x1F388),                          // 🎈
    String.fromCodePoint(0x1F44F),
    String.fromCodePoint(0x2728)                            // ✨
  ];



  var UIController = {
    estadoAtual: null,
    elementos: {},
    _timers: [],

    inicializar: function (elementos) {
      this.elementos = elementos;
      return this;
    },

    /**
     * Diz, na tela ociosa, como se começa.
     *
     * "Aproxime-se" e "Toque para registrar" são instruções opostas, e
     * a errada faz a pessoa esperar em frente a uma tela que não vai
     * reagir. Como a opção muda pelo painel e chega ao totem ao vivo, o
     * texto tem de acompanhar sem recarregar.
     */
    dizerComoComecar: function (porToque) {
      var alvo = document.querySelector('[data-comecar]');
      if (!alvo) return;
      alvo.textContent = porToque
        ? 'Toque na tela para registrar o ponto'
        : 'Aproxime-se para registrar o ponto';
    },

    /**
     * Pinta a moldura da câmera conforme o enquadramento.
     *
     * `null` volta ao repouso, 'ajustar' avisa que falta posicionar,
     * 'pronto' fecha em verde. É o único retorno que a pessoa tem antes
     * de o quadro ser enviado — sem ele, ficava adivinhando se devia se
     * aproximar ou esperar.
     */
    enquadramento: function (estado) {
      var guia = document.querySelector('#tela-camera .totem-camera__guia');
      if (!guia) return;
      guia.classList.toggle('totem-camera__guia--pronto', estado === 'pronto');
      guia.classList.toggle('totem-camera__guia--ajustar', estado === 'ajustar');
    },

    /** Troca o estado visível. Cancela timers do estado anterior. */
    mostrar: function (estado) {
      this.limparTimers();

      Object.keys(this.elementos.telas).forEach(function (nome) {
        var tela = this.elementos.telas[nome];
        if (!tela) return;
        if (nome === estado) {
          tela.removeAttribute('hidden');
          tela.classList.add('totem-tela--ativa');
        } else {
          tela.setAttribute('hidden', '');
          tela.classList.remove('totem-tela--ativa');
        }
      }, this);

      this.estadoAtual = estado;
      document.body.dataset.estado = estado;
    },

    /** Timers registrados aqui são cancelados na troca de estado. */
    agendar: function (callback, ms) {
      var id = setTimeout(callback, ms);
      this._timers.push(id);
      return id;
    },

    limparTimers: function () {
      this._timers.forEach(clearTimeout);
      this._timers = [];
    },

    // ── Relógio ────────────────────────────────────────────────
    /**
     * O relógio usa o horário do servidor, corrigido por um deslocamento
     * medido no heartbeat: o relógio do tablet costuma estar errado, e
     * exibir uma hora diferente da que foi gravada geraria contestação.
     */
    deslocamentoMs: 0,

    sincronizarRelogio: function (servidor) {
      if (!servidor || !servidor.iso) return;
      var doServidor = new Date(servidor.iso).getTime();
      this.deslocamentoMs = doServidor - Date.now();
    },

    agora: function () {
      return new Date(Date.now() + this.deslocamentoMs);
    },

    atualizarRelogios: function () {
      var agora = this.agora();
      var hora = agora.toLocaleTimeString('pt-BR');
      var data = agora.toLocaleDateString('pt-BR');

      (this.elementos.relogios || []).forEach(function (el) {
        if (el) el.textContent = hora;
      });
      (this.elementos.datas || []).forEach(function (el) {
        if (el) el.textContent = data;
      });
    },

    // ── Estado 2 — câmera ──────────────────────────────────────
    definirInstrucao: function (texto, detectando) {
      var el = this.elementos.instrucao;
      if (el) el.textContent = texto;

      var moldura = this.elementos.moldura;
      if (moldura) {
        moldura.classList.toggle('totem-camera--detectando', !!detectando);
      }
    },

    // ── Estado 3 — sucesso ─────────────────────────────────────
    /**
     * Toque curto de confirmacao, sintetizado na hora.
     *
     * Sem arquivo de audio de proposito: o totem precisa funcionar
     * offline, e um .mp3 e mais um recurso para o Service Worker
     * guardar e para a rede perder. A Web Audio API gera o som no
     * proprio aparelho, sempre disponivel.
     *
     * Duas notas subindo — o padrao que se le como "deu certo" sem
     * precisar olhar para a tela, que e o ponto: quem bateu ja esta se
     * virando para sair. No aniversario sao quatro, em acorde.
     *
     * Falha em silencio. Navegador que bloqueia audio sem gesto do
     * usuario e comum, e o ponto foi registrado de qualquer forma — a
     * tela continua sendo a confirmacao que vale.
     */
    tocarSucesso: function (festivo) {
      try {
        var Ctx = window.AudioContext || window.webkitAudioContext;
        if (!Ctx) return;
        if (!this._audio) this._audio = new Ctx();
        var ctx = this._audio;
        // O contexto nasce suspenso ate o primeiro gesto; no totem o
        // toque na tela ja aconteceu antes da batida.
        if (ctx.state === 'suspended' && ctx.resume) ctx.resume();

        // Notas com harmonico e envelope de sino.
        //
        // A versao anterior eram senoides puras com corte rapido: soava
        // a bipe de eletrodomestico, que e o oposto do que uma
        // confirmacao deve transmitir. Um sino tem o fundamental mais um
        // harmonico acima e uma cauda longa — e o que faz o som parecer
        // "acabado" em vez de interrompido.
        var notas = festivo
          ? [{ hz: 523.25, t: 0.00 }, { hz: 659.25, t: 0.13 },
             { hz: 783.99, t: 0.26 }, { hz: 1046.50, t: 0.39 }]
          : [{ hz: 659.25, t: 0.00 }, { hz: 987.77, t: 0.10 }];
        var agora = ctx.currentTime + 0.02;
        var cauda = festivo ? 1.1 : 0.75;

        var mestre = ctx.createGain();
        mestre.gain.value = festivo ? 0.20 : 0.16;
        mestre.connect(ctx.destination);

        notas.forEach(function (nota) {
          [1, 2.01].forEach(function (mult, camada) {
            var osc = ctx.createOscillator();
            var vol = ctx.createGain();
            osc.type = 'sine';
            osc.frequency.value = nota.hz * mult;
            var inicio = agora + nota.t;
            var fim = inicio + cauda;
            // O harmonico entra bem mais baixo: ele da o timbre, nao o
            // volume. Igualados, viram dissonancia.
            var pico = camada === 0 ? 1.0 : 0.22;
            vol.gain.setValueAtTime(0.0001, inicio);
            vol.gain.exponentialRampToValueAtTime(pico, inicio + 0.012);
            // Decaimento longo e suave: e a cauda que soa como sino.
            vol.gain.exponentialRampToValueAtTime(0.0001, fim);
            osc.connect(vol);
            vol.connect(mestre);
            osc.start(inicio);
            osc.stop(fim + 0.03);
          });
        });
      } catch (e) {
        // Som e confirmacao extra, nunca requisito.
      }
    },

    /**
     * Palmas subindo, so no aniversario.
     *
     * Duram menos que a tela de sucesso de proposito: a fila continua
     * andando, e uma animacao que passa do tempo da tela empurraria o
     * proximo da fila para dentro da festa do anterior.
     */
    _palmas: function (el) {
      if (!el) return;
      var caixa = el.querySelector('[data-palmas]');
      if (!caixa) {
        caixa = document.createElement('div');
        caixa.className = 'totem-palmas';
        caixa.setAttribute('data-palmas', '');
        el.appendChild(caixa);
      }
      caixa.innerHTML = '';
      for (var i = 0; i < 12; i += 1) {
        var s = document.createElement('span');
        s.textContent = SIMBOLOS_FESTA[i % SIMBOLOS_FESTA.length];
        s.style.left = (5 + Math.random() * 88) + '%';
        s.style.setProperty('--atraso', (Math.random() * 1.2).toFixed(2) + 's');
        s.style.setProperty('--dur', (2.2 + Math.random() * 1.4).toFixed(2) + 's');
        s.style.setProperty('--giro', Math.round(-25 + Math.random() * 50) + 'deg');
        caixa.appendChild(s);
      }
    },

    /**
     * Aniversariantes do dia na tela ociosa.
     *
     * Vem do heartbeat, e nao da abertura da pagina: o totem fica ligado
     * dias seguidos, e um texto renderizado uma vez so continuaria
     * parabenizando quem fez aniversario anteontem.
     */
    aniversariantes: function (nomes) {
      var el = document.querySelector('[data-aniversario]');
      if (!el) return;
      if (!nomes || !nomes.length) {
        el.hidden = true;
        el.textContent = '';
        return;
      }
      var lista;
      if (nomes.length === 1) {
        lista = nomes[0];
      } else if (nomes.length === 2) {
        lista = nomes[0] + ' e ' + nomes[1];
      } else {
        lista = nomes.slice(0, -1).join(', ') + ' e ' + nomes[nomes.length - 1];
      }
      var verbo = nomes.length === 1 ? ' e aniversario de ' : ' sao aniversarios de ';
      el.textContent = EMOJI_FESTA + ' Hoje' + verbo + lista + '!';
      el.hidden = false;
    },

    preencherSucesso: function (dados) {
      var el = this.elementos.sucesso;
      if (!el) return;

      var colaborador = dados.colaborador || {};
      var registro = dados.registro || {};

      this._texto(el.nome, colaborador.nome);
      this._texto(el.cpf, colaborador.cpf_mascarado);
      this._texto(el.tipo, registro.tipo_exibicao);
      this._texto(el.hora, registro.hora);
      this._texto(el.data, registro.data);
      // No aniversario a felicitacao toma o lugar da frase de sucesso:
      // as duas juntas viram parede de texto numa tela de 5 segundos.
      this._texto(el.mensagem, dados.aniversario || dados.despedida || dados.mensagem);
      this.tocarSucesso(!!dados.aniversario);
      if (dados.aniversario) {
        this._palmas(document.getElementById('tela-sucesso'));
      }
      this._texto(el.nsr, registro.nsr ? 'NSR ' + registro.nsr : '');
      this._texto(el.verificacao, registro.codigo_verificacao);

      if (el.foto) {
        if (colaborador.foto) {
          el.foto.src = colaborador.foto;
          el.foto.removeAttribute('hidden');
          if (el.iniciais) el.iniciais.setAttribute('hidden', '');
        } else {
          el.foto.setAttribute('hidden', '');
          if (el.iniciais) {
            el.iniciais.textContent = this._iniciais(colaborador.nome);
            el.iniciais.removeAttribute('hidden');
          }
        }
      }
    },

    atualizarContagem: function (segundos) {
      this._texto(
        this.elementos.contagemSucesso,
        'Retornando em ' + segundos + 's...'
      );
    },

    // ── Estado 4 — fallback por CPF ────────────────────────────
    limparFallback: function () {
      var campos = this.elementos.fallback || {};
      if (campos.cpf) campos.cpf.value = '';
      if (campos.nascimento) campos.nascimento.value = '';
      this.erroFallback('');
    },

    erroFallback: function (mensagem) {
      var el = (this.elementos.fallback || {}).erro;
      if (!el) return;
      el.textContent = mensagem || '';
      el.hidden = !mensagem;
    },

    focarFallback: function () {
      var campo = (this.elementos.fallback || {}).cpf;
      if (campo) {
        // O foco abre o teclado numérico nativo do Android.
        setTimeout(function () { campo.focus(); }, 120);
      }
    },

    // ── Estado 5 — offline ─────────────────────────────────────
    atualizarOffline: function (restante, total) {
      var minutos = Math.floor(restante / 60);
      var segundos = restante % 60;
      this._texto(
        this.elementos.offlineContagem,
        ('0' + minutos).slice(-2) + ':' + ('0' + segundos).slice(-2)
      );
      var barra = this.elementos.offlineProgresso;
      if (barra) {
        barra.style.width = ((total - restante) / total * 100) + '%';
      }
    },

    // ── Erro ───────────────────────────────────────────────────
    mostrarErro: function (mensagem, permiteFallback) {
      this._texto(this.elementos.erroMensagem, mensagem);
      var botao = this.elementos.erroFallbackBotao;
      if (botao) botao.hidden = !permiteFallback;
      this.mostrar('erro');
    },

    // ── Utilitários ────────────────────────────────────────────
    _texto: function (el, valor) {
      if (el) el.textContent = valor || '';
    },

    _iniciais: function (nome) {
      if (!nome) return '?';
      var partes = nome.trim().split(/\s+/);
      if (partes.length === 1) return partes[0].slice(0, 2).toUpperCase();
      return (partes[0][0] + partes[partes.length - 1][0]).toUpperCase();
    },

    /** Máscara de CPF aplicada durante a digitação. */
    mascararCPF: function (valor) {
      var d = (valor || '').replace(/\D/g, '').slice(0, 11);
      if (d.length > 9) return d.replace(/(\d{3})(\d{3})(\d{3})(\d+)/, '$1.$2.$3-$4');
      if (d.length > 6) return d.replace(/(\d{3})(\d{3})(\d+)/, '$1.$2.$3');
      if (d.length > 3) return d.replace(/(\d{3})(\d+)/, '$1.$2');
      return d;
    },

    mascararData: function (valor) {
      var d = (valor || '').replace(/\D/g, '').slice(0, 8);
      if (d.length > 4) return d.replace(/(\d{2})(\d{2})(\d+)/, '$1/$2/$3');
      if (d.length > 2) return d.replace(/(\d{2})(\d+)/, '$1/$2');
      return d;
    }
  };

  global.KronusUI = UIController;
})(window);
