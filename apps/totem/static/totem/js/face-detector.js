/**
 * Kronus — detecção de presença facial no client-side.
 *
 * O tablet apenas **detecta** que há um rosto enquadrado; quem
 * **reconhece** é o servidor, com ArcFace. Essa divisão é o que permite
 * rodar num aparelho de 3 GB de RAM.
 *
 * Usa face-api.js com TinyFaceDetector quando os modelos estão em
 * `static/totem/js/models/`. Sem eles, cai para um detector de
 * luminância — que **acorda a tela, mas não dispara reconhecimento**.
 *
 * ── Por que tanta condição antes de enviar um frame ──────────────
 *
 * A primeira versão enviava ao servidor no primeiro frame em que
 * "detectou" algo. Na prática, uma mão passando, uma sombra ou alguém
 * andando ao fundo disparavam o reconhecimento; como não havia rosto,
 * a tela pedia CPF e data de nascimento. Além de irritante, isso
 * degrada a segurança: acostuma a fila a usar o fallback.
 *
 * Agora um frame só é enviado quando o rosto:
 *
 *   1. é detectado pelo TinyFaceDetector (não pela heurística);
 *   2. ocupa área suficiente do quadro — perto o bastante para valer
 *      um embedding decente;
 *   3. está razoavelmente centralizado;
 *   4. persiste por N leituras seguidas — o que descarta o transeunte.
 */
(function (global) {
  'use strict';

  var FaceDetector = {
    pronto: false,
    modo: 'nenhum',        // 'faceapi' | 'heuristico'
    opcoes: null,
    _referencia: null,     // baseline de luminância do modo heurístico
    _seguidos: 0,          // leituras consecutivas com rosto válido

    /** Confiança mínima do TinyFaceDetector. */
    CONFIANCA_MINIMA: 0.55,

    /**
     * Fração mínima da largura do quadro que o rosto deve ocupar.
     *
     * 0.18 corresponde, num quadro de 640 px, a um rosto de ~115 px —
     * aproximadamente 60 cm da câmera. Abaixo disso o recorte tem
     * poucos pixels úteis e o embedding sai pobre, o que aparece
     * depois como "não reconheci" numa pessoa cadastrada.
     */
    LARGURA_MINIMA_ROSTO: 0.18,

    /** Rosto acima disso está perto demais (recorte cortado). */
    LARGURA_MAXIMA_ROSTO: 0.85,

    /**
     * Distância máxima do centro, em fração da largura.
     *
     * Quem está de passagem aparece na borda; quem veio bater ponto
     * se posiciona na frente.
     */
    DESVIO_MAXIMO_CENTRO: 0.28,

    /**
     * Leituras consecutivas exigidas antes de enviar.
     *
     * A ~500 ms por leitura, 3 significam ~1,5 s parado em frente à
     * câmera. É o que separa "veio bater ponto" de "passou na frente".
     */
    LEITURAS_PARA_CONFIRMAR: 3,

    /**
     * Carrega os modelos. Nunca rejeita: um totem que não inicia é pior
     * do que um totem em modo degradado.
     */
    carregar: function (caminhoModelos) {
      var self = this;

      if (typeof faceapi === 'undefined') {
        console.warn('[Kronus] face-api.js ausente — deteccao heuristica ativada.');
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
     * Analisa o canvas.
     *
     * Resolve com:
     *   presenca  — há algo/alguém: serve para acordar a tela
     *   pronto    — rosto válido e estável: pode enviar ao servidor
     *   motivo    — por que não está pronto, para a instrução na tela
     */
    detectar: function (canvas) {
      var vazio = { presenca: false, pronto: false, confianca: 0, motivo: 'vazio' };
      if (!canvas) return Promise.resolve(vazio);

      if (this.modo === 'faceapi') {
        return this._detectarRosto(canvas);
      }

      // Modo degradado: acorda a tela, mas **nunca** declara pronto.
      // Sem detector de rosto de verdade, enviar ao servidor com base em
      // luminância é o que fazia o totem pedir CPF a cada sombra.
      var heuristico = this._detectarHeuristico(canvas);
      return Promise.resolve({
        presenca: heuristico.detectado,
        pronto: false,
        confianca: heuristico.confianca,
        motivo: 'sem_detector'
      });
    },

    _detectarRosto: function (canvas) {
      var self = this;
      var largura = canvas.width || 1;

      return faceapi
        .detectSingleFace(canvas, this.opcoes)
        .then(function (deteccao) {
          if (!deteccao) {
            self._seguidos = 0;
            return { presenca: false, pronto: false, confianca: 0, motivo: 'sem_rosto' };
          }

          var caixa = deteccao.box;
          var proporcao = caixa.width / largura;
          var centroRosto = caixa.x + caixa.width / 2;
          var desvio = Math.abs(centroRosto - largura / 2) / largura;

          var motivo = null;
          if (proporcao < self.LARGURA_MINIMA_ROSTO) motivo = 'longe';
          else if (proporcao > self.LARGURA_MAXIMA_ROSTO) motivo = 'perto';
          else if (desvio > self.DESVIO_MAXIMO_CENTRO) motivo = 'descentralizado';

          if (motivo) {
            // Há rosto — a tela acorda —, mas o enquadramento não serve.
            self._seguidos = 0;
            return {
              presenca: true, pronto: false,
              confianca: deteccao.score, caixa: caixa, motivo: motivo
            };
          }

          self._seguidos += 1;
          return {
            presenca: true,
            pronto: self._seguidos >= self.LEITURAS_PARA_CONFIRMAR,
            confianca: deteccao.score,
            caixa: caixa,
            proporcao: proporcao,
            motivo: self._seguidos >= self.LEITURAS_PARA_CONFIRMAR ? 'ok' : 'estabilizando'
          };
        })
        .catch(function () {
          self._seguidos = 0;
          return { presenca: false, pronto: false, confianca: 0, motivo: 'erro' };
        });
    },

    /**
     * Detector de reserva: variação de luminância na região central.
     *
     * Não distingue rosto de qualquer objeto. Por isso o seu resultado
     * só acorda a tela — nunca autoriza envio.
     */
    _detectarHeuristico: function (canvas) {
      var ctx = canvas.getContext('2d');
      var largura = canvas.width;
      var altura = canvas.height;

      var x = Math.floor(largura * 0.25);
      var y = Math.floor(altura * 0.20);
      var w = Math.floor(largura * 0.50);
      var h = Math.floor(altura * 0.60);

      var dados = ctx.getImageData(x, y, w, h).data;
      var soma = 0;
      for (var i = 0; i < dados.length; i += 64) {
        soma += (dados[i] * 0.299 + dados[i + 1] * 0.587 + dados[i + 2] * 0.114);
      }
      var media = soma / (dados.length / 64);

      if (this._referencia === null) {
        this._referencia = media;
        return { detectado: false, confianca: 0 };
      }

      var variacao = Math.abs(media - this._referencia) / Math.max(this._referencia, 1);
      this._referencia = this._referencia * 0.95 + media * 0.05;

      var detectado = variacao > 0.10 && media > 30;
      return {
        detectado: detectado,
        confianca: detectado ? Math.min(variacao * 5, 1) : 0
      };
    },

    /** Texto de orientação para cada motivo de recusa. */
    instrucaoPara: function (motivo) {
      var textos = {
        sem_rosto: 'Posicione o rosto no centro',
        longe: 'Aproxime-se um pouco',
        perto: 'Afaste-se um pouco',
        descentralizado: 'Centralize o rosto',
        estabilizando: 'Fique parado…',
        sem_detector: 'Posicione o rosto no centro',
        ok: 'Identificando…'
      };
      return textos[motivo] || 'Posicione o rosto no centro';
    },

    /** Zera o estado ao sair do ocioso ou após um envio. */
    reiniciar: function () {
      this._referencia = null;
      this._seguidos = 0;
    }
  };

  global.KronusFaceDetector = FaceDetector;
})(window);
