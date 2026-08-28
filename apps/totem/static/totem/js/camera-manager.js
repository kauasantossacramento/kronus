/**
 * Kronus — gerenciamento da câmera do totem.
 *
 * Alvo: Positivo Tab 7 Vision (7", 1024x600, 3 GB de RAM), portrait.
 *
 * A câmera é o recurso mais caro do equipamento. Este módulo garante que
 * ela seja aberta uma única vez e liberada assim que a interação termina
 * — deixar o stream ativo no ocioso derruba a bateria e esquenta o
 * tablet a ponto de degradar o desempenho ao longo do turno.
 */
(function (global) {
  'use strict';

  var CameraManager = {
    stream: null,
    video: null,
    canvas: null,
    contexto: null,

    /** Resolução de captura — 640x480 é o suficiente para o ArcFace. */
    LARGURA: 640,
    ALTURA: 480,

    /** Resolução reduzida usada na detecção (Seção 6.5.2, item 4). */
    LARGURA_DETECCAO: 320,
    ALTURA_DETECCAO: 240,

    /**
     * Prepara os elementos. Não abre a câmera ainda.
     */
    inicializar: function (elementoVideo) {
      this.video = elementoVideo;
      this.canvas = document.createElement('canvas');
      this.canvas.width = this.LARGURA;
      this.canvas.height = this.ALTURA;
      this.contexto = this.canvas.getContext('2d', { willReadFrequently: true });

      this.canvasDeteccao = document.createElement('canvas');
      this.canvasDeteccao.width = this.LARGURA_DETECCAO;
      this.canvasDeteccao.height = this.ALTURA_DETECCAO;
      this.contextoDeteccao = this.canvasDeteccao.getContext('2d', { willReadFrequently: true });
    },

    /**
     * Abre a câmera frontal. Idempotente: chamar duas vezes não abre
     * dois streams.
     */
    abrir: function () {
      var self = this;
      if (this.stream) return Promise.resolve(this.stream);

      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        return Promise.reject(new Error('Câmera não suportada neste dispositivo.'));
      }

      // Duas tentativas, da mais especifica para a mais tolerante.
      //
      // Tablet de baixo custo costuma recusar `facingMode` ou a dica de
      // resolucao com `OverconstrainedError` — e a mensagem que chegava
      // ao operador era so "nao foi possivel acessar a camera", sem
      // dizer o que tentar. Pedir menos na segunda tentativa resolve o
      // caso comum sem esconder a causa quando o problema e outro.
      var pedir = function (restricoes) {
        return navigator.mediaDevices.getUserMedia(restricoes);
      };

      return pedir({
        video: {
          facingMode: 'user',
          width: { ideal: self.LARGURA },
          height: { ideal: self.ALTURA }
        },
        audio: false
      })
        .catch(function (erro) {
          var recuperavel = ['OverconstrainedError', 'ConstraintNotSatisfiedError',
                             'NotFoundError', 'DevicesNotFoundError'];
          if (recuperavel.indexOf(erro && erro.name) === -1) throw erro;
          console.warn('[Kronus] camera: tentando sem restricoes —', erro.name);
          return pedir({ video: true, audio: false });
        })
        .then(function (stream) {
          self.stream = stream;
          self.video.srcObject = stream;
          return self.video.play().then(function () {
            return stream;
          });
        });
    },

    /**
     * Libera a câmera. Chamado ao voltar para o ocioso e ao sair da
     * página — sem isso o LED da câmera fica aceso indefinidamente, o
     * que assusta o usuário e consome bateria.
     */
    fechar: function () {
      if (this.stream) {
        this.stream.getTracks().forEach(function (track) {
          track.stop();
        });
        this.stream = null;
      }
      if (this.video) {
        this.video.srcObject = null;
      }
    },

    get ativa() {
      return this.stream !== null;
    },

    /** Frame reduzido, para a detecção rodar barato no client-side. */
    frameParaDeteccao: function () {
      if (!this.video || this.video.readyState < 2) return null;
      this.contextoDeteccao.drawImage(
        this.video, 0, 0, this.LARGURA_DETECCAO, this.ALTURA_DETECCAO
      );
      return this.canvasDeteccao;
    },

    /**
     * Frame em resolução plena, comprimido para envio ao servidor.
     *
     * Qualidade 0.7 reduz o payload em cerca de 60% sem prejuízo
     * perceptível para o embedding (Seção 6.5.2, item 5).
     */
    capturarJPEG: function (qualidade) {
      if (!this.video || this.video.readyState < 2) return null;
      this.contexto.drawImage(this.video, 0, 0, this.LARGURA, this.ALTURA);
      return this.canvas.toDataURL('image/jpeg', qualidade || 0.7);
    },

    /** Diagnóstico exibido na tela de erro do totem. */
    descreverErro: function (erro) {
      var nome = (erro && erro.name) || '';
      if (nome === 'NotAllowedError' || nome === 'PermissionDeniedError') {
        return 'Permissão de câmera negada. Libere o acesso nas configurações do dispositivo.';
      }
      if (nome === 'NotFoundError' || nome === 'DevicesNotFoundError') {
        return 'Nenhuma câmera encontrada neste equipamento.';
      }
      if (nome === 'NotReadableError' || nome === 'TrackStartError') {
        return 'A câmera está em uso por outro aplicativo.';
      }
      if (nome === 'OverconstrainedError' || nome === 'ConstraintNotSatisfiedError') {
        return 'A câmera não aceita a configuração pedida.';
      }
      if (nome === 'SecurityError') {
        return 'O navegador bloqueou a câmera nesta página.';
      }
      // Guardar o nome do erro no fim da mensagem: sem ele, todo
      // problema desconhecido vira a mesma frase e o suporte fica sem
      // por onde começar.
      return 'Não foi possível acessar a câmera'
        + (nome ? ' (' + nome + ').' : '.');
    }
  };

  global.KronusCamera = CameraManager;
})(window);
