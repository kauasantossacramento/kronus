/**
 * Kronus — detecção de presença facial no client-side.
 *
 * O tablet apenas **detecta** que há um rosto enquadrado; quem
 * **reconhece** é o servidor, com ArcFace (Seção 6.5.2, item 6). Essa
 * divisão é o que permite rodar em um aparelho de 3 GB de RAM.
 *
 * Usa face-api.js com TinyFaceDetector (~190 KB) quando os modelos estão
 * presentes em `static/totem/js/models/`. Sem eles — ou se a biblioteca
 * falhar ao carregar — cai para um detector de movimento e luminância,
 * que dispara a captura sem travar o equipamento. A precisão real vem do
 * servidor de qualquer forma; o detector local só decide *quando* enviar.
 */
(function (global) {
  'use strict';

  var FaceDetector = {
    pronto: false,
    modo: 'nenhum',        // 'faceapi' | 'heuristico'
    opcoes: null,
    _referencia: null,     // baseline de luminância do modo heurístico

    /** Confiança mínima para considerar que há alguém enquadrado. */
    CONFIANCA_MINIMA: 0.7,

    /**
     * Carrega os modelos. Nunca rejeita: um totem que não inicia é pior
     * do que um totem em modo degradado.
     */
    carregar: function (caminhoModelos) {
      var self = this;

      if (typeof faceapi === 'undefined') {
        console.warn('[Kronus] face-api.js ausente — detecção heurística ativada.');
        self.modo = 'heuristico';
        self.pronto = true;
        return Promise.resolve(self.modo);
      }

      return faceapi.nets.tinyFaceDetector
        .loadFromUri(caminhoModelos)
        .then(function () {
          self.opcoes = new faceapi.TinyFaceDetectorOptions({
            inputSize: 224,          // múltiplo de 32; barato o bastante
            scoreThreshold: self.CONFIANCA_MINIMA
          });
          self.modo = 'faceapi';
          self.pronto = true;
          console.info('[Kronus] TinyFaceDetector carregado.');
          return self.modo;
        })
        .catch(function (erro) {
          console.warn('[Kronus] Falha ao carregar os modelos:', erro);
          self.modo = 'heuristico';
          self.pronto = true;
          return self.modo;
        });
    },

    /**
     * Verifica se há rosto no canvas.
     * Resolve com `{ detectado, confianca, caixa }`.
     */
    detectar: function (canvas) {
      if (!canvas) return Promise.resolve({ detectado: false, confianca: 0 });

      if (this.modo === 'faceapi') {
        return faceapi
          .detectSingleFace(canvas, this.opcoes)
          .then(function (deteccao) {
            if (!deteccao) return { detectado: false, confianca: 0 };
            return {
              detectado: true,
              confianca: deteccao.score,
              caixa: deteccao.box
            };
          })
          .catch(function () {
            return { detectado: false, confianca: 0 };
          });
      }

      return Promise.resolve(this._detectarHeuristico(canvas));
    },

    /**
     * Detector de reserva: compara a luminância média da região central
     * com uma referência móvel. Alguém que se aproxima da câmera altera
     * essa média de forma consistente.
     *
     * Não distingue rosto de qualquer objeto — por isso é apenas um
     * gatilho para enviar o frame. O servidor decide o resto.
     */
    _detectarHeuristico: function (canvas) {
      var ctx = canvas.getContext('2d');
      var largura = canvas.width;
      var altura = canvas.height;

      // Região central: 50% da largura, 60% da altura.
      var x = Math.floor(largura * 0.25);
      var y = Math.floor(altura * 0.20);
      var w = Math.floor(largura * 0.50);
      var h = Math.floor(altura * 0.60);

      var dados = ctx.getImageData(x, y, w, h).data;
      var soma = 0;
      // Amostragem a cada 16 pixels: precisão suficiente, custo baixo.
      for (var i = 0; i < dados.length; i += 64) {
        soma += (dados[i] * 0.299 + dados[i + 1] * 0.587 + dados[i + 2] * 0.114);
      }
      var media = soma / (dados.length / 64);

      if (this._referencia === null) {
        this._referencia = media;
        return { detectado: false, confianca: 0 };
      }

      var variacao = Math.abs(media - this._referencia) / Math.max(this._referencia, 1);
      // A referência acompanha a luz ambiente lentamente, para que a
      // variação natural do dia não vire detecção contínua.
      this._referencia = this._referencia * 0.95 + media * 0.05;

      var detectado = variacao > 0.08 && media > 30;
      return {
        detectado: detectado,
        confianca: detectado ? Math.min(variacao * 5, 1) : 0
      };
    },

    /** Zera a referência ao sair do ocioso. */
    reiniciar: function () {
      this._referencia = null;
    }
  };

  global.KronusFaceDetector = FaceDetector;
})(window);
