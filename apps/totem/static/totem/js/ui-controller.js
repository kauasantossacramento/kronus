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
      this._texto(el.mensagem, dados.mensagem);
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
