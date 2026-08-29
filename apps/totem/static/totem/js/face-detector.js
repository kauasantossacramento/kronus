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
    opcoesPresenca: null,
    _referencia: null,     // baseline de luminância do modo heurístico
    _seguidos: 0,          // leituras consecutivas com rosto válido

    /** Confiança mínima do TinyFaceDetector para valer um envio. */
    CONFIANCA_MINIMA: 0.55,

    /**
     * Confiança mínima para apenas **acordar a tela**.
     *
     * Mais baixa de propósito: acordar à toa custa uma tela acesa que
     * volta sozinha ao ocioso, enquanto não acordar custa a pessoa
     * parada na frente do totem achando que ele está morto. Os dois
     * erros não têm o mesmo preço.
     *
     * Isto **não** afrouxa o envio ao servidor: `pronto` continua
     * exigindo enquadramento, distância e estabilidade, medidos com
     * `CONFIANCA_MINIMA`.
     */
    CONFIANCA_PRESENCA: 0.35,

    /**
     * Fração mínima da largura do quadro que o rosto deve ocupar.
     *
     * O ArcFace consome um recorte de 112×112. O valor anterior, 0.18,
     * era exatamente o ponto em que o recorte deixa de precisar ser
     * ampliado — num quadro de 640 px, ~115 px de rosto, algo como 60 cm
     * da câmera. Funcionava no papel e mal na prática: um recorte no
     * limite não tem detalhe sobrando, e detalhe é o que separa duas
     * pessoas parecidas. Foi nessa faixa que apareceram as
     * identificações no fio do limiar.
     *
     * O valor de hoje vem de medição no equipamento instalado, e não de
     * conta: com 0.28 o totem começava a tentar a **80 cm**. A estimativa
     * anterior, de ~40 cm, saiu de supor um quadro de 640 px — a câmera
     * do tablet tem outro campo de visão, e a conta não sobreviveu ao
     * contato com o aparelho.
     *
     * A largura do rosto no quadro é inversamente proporcional à
     * distância, então 70 cm pede 0.28 × 80/70 ≈ 0.32.
     *
     * Por que insistir em perto: o recorte chega ao modelo com mais
     * pixels reais, e é o detalhe que separa duas pessoas parecidas. O
     * custo é pedir "aproxime-se" com mais frequência — a instrução
     * aparece na tela e a pessoa dá um passo. O outro erro, o de
     * identificar quem não é, não avisa ninguém.
     */
    LARGURA_MINIMA_ROSTO: 0.32,

    /**
     * Rosto acima disso está perto demais.
     *
     * Era 0.85, e recusava quem chegava bem perto — o gesto natural de
     * quem quer ser reconhecido logo. A pessoa via a tela sem reagir e
     * precisava tocar nela, que é justamente o que o reconhecimento
     * automático existe para evitar.
     *
     * 0.95 recusa só o absurdo: rosto colado na lente, em que sobra
     * pouco além de testa e queixo. Um recorte grande demais o servidor
     * reenquadra sozinho — ele detecta e corta de novo antes do
     * embedding.
     */
    LARGURA_MAXIMA_ROSTO: 0.95,

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
     * Duas, e não três. A ~150 ms por leitura com a câmera ativa, três
     * eram meio segundo de espera depois de o rosto já estar enquadrado
     * — tempo em que a pessoa acha que o totem não a viu e se mexe,
     * zerando a contagem. Duas leituras seguidas continuam descartando
     * quem passa na frente, porque o enquadramento e a distância já
     * precisam estar certos nas duas.
     */
    LEITURAS_PARA_CONFIRMAR: 2,

    /**
     * Carrega os modelos. Nunca rejeita: um totem que não inicia é pior
     * do que um totem em modo degradado.
     */
    /**
     * Espera o face-api.js aparecer.
     *
     * O script e `defer`: pode nao ter terminado de executar quando o
     * app inicia. A versao anterior conferia `typeof faceapi` uma unica
     * vez e, se ainda nao estivesse la, desistia **em definitivo** —
     * escolhendo o modo degradado por causa de alguns milissegundos de
     * diferenca. Como o modo degradado nunca declara um rosto pronto, o
     * totem parava de enviar imagem ao servidor e nao reconhecia mais
     * ninguem, sem nada na tela dizendo por que.
     *
     * Uma corrida assim quase nunca aparece em rede local, onde o
     * arquivo vem em milissegundos: ela espera a rede real.
     */
    _esperarFaceApi: function (limiteMs) {
      if (typeof faceapi !== 'undefined') return Promise.resolve(true);

      return new Promise(function (resolver) {
        var prazo = Date.now() + (limiteMs || 15000);
        var conferir = function () {
          if (typeof faceapi !== 'undefined') return resolver(true);
          if (Date.now() > prazo) return resolver(false);
          setTimeout(conferir, 100);
        };
        conferir();
      });
    },

    carregar: function (caminhoModelos) {
      var self = this;

      return this._esperarFaceApi(15000).then(function (chegou) {
        if (!chegou) {
          console.error('[Kronus] face-api.js nao carregou — o totem NAO vai '
            + 'reconhecer rostos. Verifique /diagnostico/.');
          self.modo = 'heuristico';
          self.pronto = true;
          self.motivoDegradado = 'face-api.js nao carregou';
          return self.modo;
        }
        return self._carregarModelos(caminhoModelos);
      });
    },

    _carregarModelos: function (caminhoModelos) {
      var self = this;
      return faceapi.nets.tinyFaceDetector
        .loadFromUri(caminhoModelos)
        .then(function () {
          self.opcoes = new faceapi.TinyFaceDetectorOptions({
            inputSize: 224,          // múltiplo de 32; barato o bastante
            scoreThreshold: self.CONFIANCA_MINIMA
          });
          self.opcoesPresenca = new faceapi.TinyFaceDetectorOptions({
            inputSize: 224,
            scoreThreshold: self.CONFIANCA_PRESENCA
          });
          self.modo = 'faceapi';
          self.pronto = true;
          console.info('[Kronus] TinyFaceDetector carregado.');
          return self.modo;
        })
        .catch(function (erro) {
          console.error('[Kronus] Falha ao carregar os modelos:', erro);
          self.modo = 'heuristico';
          self.pronto = true;
          self.motivoDegradado = 'modelos nao carregaram: ' + (erro && erro.message);
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
    detectar: function (canvas, sensivel) {
      var vazio = { presenca: false, pronto: false, confianca: 0, motivo: 'vazio' };
      if (!canvas) return Promise.resolve(vazio);

      if (this.modo === 'faceapi') {
        return this._detectarRosto(canvas, sensivel);
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

    _detectarRosto: function (canvas, sensivel) {
      var self = this;
      var largura = canvas.width || 1;
      var opcoes = (sensivel && this.opcoesPresenca) || this.opcoes;

      return faceapi
        .detectSingleFace(canvas, opcoes)
        .then(function (deteccao) {
          if (!deteccao) {
            self._seguidos = 0;
            // Sem rosto detectado, a heuristica ainda decide se ha
            // ALGUEM ali. O TinyFaceDetector perde o rosto colado na
            // lente, e era isso que deixava a tela parada esperando um
            // toque justamente de quem tinha chegado mais perto.
            //
            // Acordar a tela e barato; enviar ao servidor continua
            // exigindo rosto detectado e enquadrado.
            var perto = self._detectarHeuristico(canvas);
            return {
              presenca: perto.detectado,
              pronto: false,
              confianca: 0,
              motivo: perto.detectado ? 'ajustar' : 'sem_rosto'
            };
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

          if (sensivel && deteccao.score < self.CONFIANCA_MINIMA) {
            // Serviu para acordar a tela, nao para contar como leitura
            // boa: quem decide o envio e sempre o criterio rigoroso.
            self._seguidos = 0;
            return {
              presenca: true, pronto: false,
              confianca: deteccao.score, caixa: caixa, motivo: 'estabilizando'
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
        longe: 'Aproxime-se da câmera',
        perto: 'Afaste-se um pouco',
        ajustar: 'Centralize o rosto na moldura',
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
