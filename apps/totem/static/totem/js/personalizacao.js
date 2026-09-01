/**
 * Kronus — identidade visual do totem, vinda do servidor.
 *
 * A API já enviava `cor_primaria` e `cor_secundaria` desde o começo —
 * **e o totem nunca as lia**. O quiosque ficava azul-Kronus em todas as
 * empresas, e a personalização que o RH configurava não aparecia onde
 * ela mais importa: a tela que o colaborador vê todo dia.
 *
 * Cuida de quatro coisas:
 *   cores      variáveis CSS aplicadas na raiz
 *   logo       tamanho, deslocamento e regra CSS livre
 *   slides     tela de ociosidade com várias imagens e transição
 *   som        confirmação sonora ao registrar o ponto
 */
(function (global) {
  'use strict';

  var Personalizacao = {
    config: null,
    _slides: [],
    _indice: 0,
    _timerSlides: null,
    _audio: null,

    aplicar: function (empresa, elementos) {
      if (!empresa) return;
      this.config = empresa;
      this._cores(empresa);
      this._logo(empresa, elementos);
      this._textos(empresa);
      this._slides_iniciar(empresa, elementos);
      this._som_preparar(empresa);
    },

    // ── Textos e assinatura ──────────────────────────────────
    // Aplicados aqui, e nao so no HTML renderizado, para que uma
    // alteracao no painel apareca na recarga da configuracao — sem
    // ninguem precisar reiniciar o tablet da portaria.
    _textos: function (empresa) {
      if (empresa.slogan) {
        var frase = document.querySelector('.totem-idle__tagline');
        if (frase) frase.textContent = empresa.slogan;
      }
      var tamanhos = [
        ['.totem-idle__mensagem', '--totem-msg-px', empresa.msg_boas_vindas_px],
        ['.totem-idle__tagline', '--totem-slogan-px', empresa.slogan_px]
      ];
      tamanhos.forEach(function (par) {
        if (!par[2]) return;
        var alvo = document.querySelector(par[0]);
        if (alvo) alvo.style.setProperty(par[1], par[2] + 'px');
      });

      if (empresa.msg_sucesso_px) {
        var msg = document.getElementById('sucesso-mensagem');
        if (msg) msg.style.fontSize = empresa.msg_sucesso_px + 'px';
      }

      if (empresa.assinatura_altura_px) {
        var assinatura = document.querySelector('.totem-assinatura');
        if (assinatura) {
          assinatura.style.setProperty(
            '--totem-assinatura-altura', empresa.assinatura_altura_px + 'px'
          );
        }
      }
    },

    // ── Cores ────────────────────────────────────────────────
    _cores: function (empresa) {
      var raiz = document.documentElement;
      if (empresa.cor_primaria) {
        raiz.style.setProperty('--kronus-primary-500', empresa.cor_primaria);
        raiz.style.setProperty('--kronus-primary-600', empresa.cor_primaria);
        // O fundo do totem deriva da cor primária escurecida. Sem isto,
        // uma empresa de identidade clara ficava com texto branco sobre
        // fundo claro.
        raiz.style.setProperty('--kronus-primary-900', this._escurecer(empresa.cor_primaria, 0.45));
        raiz.style.setProperty('--kronus-primary-800', this._escurecer(empresa.cor_primaria, 0.30));
      }
      if (empresa.cor_secundaria) {
        raiz.style.setProperty('--kronus-gold-500', empresa.cor_secundaria);
        raiz.style.setProperty('--kronus-gold-400', this._clarear(empresa.cor_secundaria, 0.20));
      }
    },

    _componentes: function (hex) {
      var limpo = (hex || '').replace('#', '');
      if (limpo.length === 3) {
        limpo = limpo[0] + limpo[0] + limpo[1] + limpo[1] + limpo[2] + limpo[2];
      }
      if (limpo.length !== 6) return null;
      return [
        parseInt(limpo.slice(0, 2), 16),
        parseInt(limpo.slice(2, 4), 16),
        parseInt(limpo.slice(4, 6), 16)
      ];
    },

    _para_hex: function (partes) {
      return '#' + partes.map(function (v) {
        var n = Math.max(0, Math.min(255, Math.round(v)));
        return (n < 16 ? '0' : '') + n.toString(16);
      }).join('');
    },

    _escurecer: function (hex, fator) {
      var rgb = this._componentes(hex);
      if (!rgb) return hex;
      return this._para_hex(rgb.map(function (v) { return v * (1 - fator); }));
    },

    _clarear: function (hex, fator) {
      var rgb = this._componentes(hex);
      if (!rgb) return hex;
      return this._para_hex(rgb.map(function (v) { return v + (255 - v) * fator; }));
    },

    // ── Logo ─────────────────────────────────────────────────
    _logo: function (empresa, elementos) {
      // A tela do totem tem mais de um ponto de marca — ociosidade,
      // camera e confirmacao. `querySelector` pegava so o primeiro, e a
      // logo aparecia trocada numa tela e antiga nas outras.
      var alvos = document.querySelectorAll('[data-kronus-logo]');
      if (elementos && elementos.logo) alvos = [elementos.logo];
      if (!alvos.length) return;

      var altura = empresa.logo_altura_px || 64;
      var deslocamento = empresa.logo_deslocamento_px || 0;

      Array.prototype.forEach.call(alvos, function (alvo) {
        if (empresa.logo) {
          alvo.innerHTML = '';
          var img = document.createElement('img');
          img.src = empresa.logo;
          img.alt = empresa.nome || '';
          img.className = 'totem-logo-img';
          alvo.appendChild(img);
        }
        alvo.style.setProperty('--totem-logo-altura', altura + 'px');
        alvo.style.transform = 'translateY(' + deslocamento + 'px)';
      });

      // Regra livre do administrador. Aplicada por uma folha de estilo
      // propria, e nao inline, para que valha tambem para o SVG da
      // marca do Kronus quando a empresa nao tem logo — o pedido era
      // que a cor valesse para toda a estrutura.
      if (empresa.logo_css) {
        var estilo = document.getElementById('kronus-logo-css')
          || document.createElement('style');
        estilo.id = 'kronus-logo-css';
        estilo.textContent =
          '[data-kronus-logo], [data-kronus-logo] img, [data-kronus-logo] svg {'
          + empresa.logo_css + '}';
        if (!estilo.parentNode) document.head.appendChild(estilo);
      }
    },

    // ── Slides da tela de ociosidade ─────────────────────────
    _slides_iniciar: function (empresa, elementos) {
      var alvo = (elementos && elementos.idle) || document.querySelector('[data-kronus-slides]');
      if (!alvo) return;

      // Para o rodizio anterior ANTES de qualquer coisa. Sem isto, cada
      // atualizacao de configuracao deixava mais um temporizador vivo, e
      // os slides passavam a trocar cada vez mais rapido.
      if (this._timerSlides) {
        clearInterval(this._timerSlides);
        this._timerSlides = null;
      }

      // O acervo entra junto dos slides da empresa, ou sozinho, ou
      // nao entra — conforme o que ela escolheu no painel.
      //
      // As imagens do acervo levam a frase do periodo como legenda: a
      // frase sozinha numa tela vazia fica solta, e a imagem sozinha
      // nao diz nada. Juntas viram o cartao que a pessoa le enquanto
      // decide tocar.
      var ambiente = (empresa.ambiente && empresa.ambiente.imagens) || [];
      var frases = (empresa.ambiente && empresa.ambiente.frases) || [];
      // A frase nao vai mais como legenda do slide.
      //
      // Como legenda ela vivia no topo da tela, longe da marca e do
      // relogio, e trocava junto com a imagem. Agora ela mora no bloco
      // de conteudo, abaixo do aviso de toque — e o JS a troca no mesmo
      // ritmo dos slides.
      this._frases = frases;
      var doAcervo = ambiente.map(function (img) {
        return { url: img.url, legenda: '', clara: !!img.clara };
      });

      var proprios = empresa.slides || [];
      if (empresa.ambiente && empresa.ambiente.exclusivo) {
        this._slides = doAcervo;
      } else {
        this._slides = proprios.concat(doAcervo);
      }
      this._indice = 0;

      // Sem slides, limpa o que havia. Sair antes deixava a imagem
      // antiga na tela depois de ela ter sido removida no painel.
      if (!this._slides.length) {
        alvo.innerHTML = '';
        alvo.removeAttribute('data-transicao');
        return;
      }

      var transicao = empresa.slides_transicao || 'fade';
      var segundos = empresa.slides_segundos || 8;

      alvo.innerHTML = '';
      alvo.setAttribute('data-transicao', transicao);

      this._slides.forEach(function (slide, indice) {
        var figura = document.createElement('figure');
        figura.className = 'totem-slide'
          + (indice === 0 ? ' ativo' : '')
          // Foto clara apaga logo branca. A marca escurece enquanto ela
          // estiver na tela — a claridade foi medida na entrada da
          // imagem, entao aqui e so ler.
          + (slide.clara ? ' totem-slide--clara' : '');
        figura.style.backgroundImage = 'url("' + slide.url + '")';
        if (slide.legenda) {
          var legenda = document.createElement('figcaption');
          legenda.textContent = slide.legenda;
          figura.appendChild(legenda);
        }

        alvo.appendChild(figura);
      });

      // Uma imagem só não precisa de rotação — e o timer ficaria
      // rodando à toa numa tela que fica ligada o dia inteiro.
      if (this._slides.length < 2) return;

      var self = this;
      this._parar_slides();
      this._marcar_claridade(alvo);
      this._mostrar_frase(0);
      this._timerSlides = setInterval(function () {
        var figuras = alvo.querySelectorAll('.totem-slide');
        figuras[self._indice].classList.remove('ativo');
        self._indice = (self._indice + 1) % figuras.length;
        figuras[self._indice].classList.add('ativo');
        self._marcar_claridade(alvo);
        self._mostrar_frase(self._indice);
      }, segundos * 1000);
    },

    /**
     * A frase do periodo, trocando junto com a imagem.
     *
     * Reinicia a animacao de entrada a cada troca: sem isso a frase
     * nova aparecia no lugar da anterior sem transicao, e a troca lia
     * como falha de renderizacao.
     */
    _mostrar_frase: function (indice) {
      var alvo = document.querySelector('[data-frase-ambiente]');
      if (!alvo) return;
      var frases = this._frases || [];
      if (!frases.length) {
        alvo.hidden = true;
        return;
      }
      var texto = frases[indice % frases.length];
      alvo.textContent = texto;
      alvo.hidden = false;
      // Forca o reinicio da animacao: sem o reflow o navegador entende
      // que a classe nao mudou e nao reanima.
      alvo.classList.remove('totem-frase--entra');
      void alvo.offsetWidth;
      alvo.classList.add('totem-frase--entra');
    },

    /**
     * Avisa a tela que o slide atual e claro.
     *
     * A marca da empresa costuma ser branca, e sobre foto de ceu ou
     * neve ela desaparece. A alternativa seria uma sombra permanente
     * atras da logo, que sujaria a marca nas fotos escuras — que sao a
     * maioria.
     *
     * A classe vai no `<body>`, e nao na figura: quem precisa reagir e
     * a logo, que fica fora do contêiner dos slides.
     */
    _marcar_claridade: function (alvo) {
      var atual = alvo.querySelector('.totem-slide.ativo');
      var clara = !!(atual && atual.classList.contains('totem-slide--clara'));
      document.body.classList.toggle('totem-fundo-claro', clara);
    },

    _parar_slides: function () {
      if (this._timerSlides) {
        clearInterval(this._timerSlides);
        this._timerSlides = null;
      }
    },

    // ── Som de confirmação ───────────────────────────────────
    _som_preparar: function (empresa) {
      if (!empresa.som_confirmacao) return;
      try {
        var Contexto = global.AudioContext || global.webkitAudioContext;
        if (Contexto) this._audio = new Contexto();
      } catch (erro) {
        console.warn('[Kronus] Audio indisponivel:', erro);
      }
    },

    /**
     * Toca a confirmação.
     *
     * Sintetizado em vez de tocar um arquivo: são dois tons curtos, e
     * gerá-los evita mais um asset para o Service Worker cachear e mais
     * uma requisição que pode falhar num totem offline.
     */
    tocarConfirmacao: function (sucesso) {
      if (!this._audio) return;
      try {
        if (this._audio.state === 'suspended') this._audio.resume();

        var notas = sucesso ? [880, 1320] : [440, 330];
        var self = this;
        notas.forEach(function (frequencia, indice) {
          var oscilador = self._audio.createOscillator();
          var ganho = self._audio.createGain();
          oscilador.type = 'sine';
          oscilador.frequency.value = frequencia;
          var inicio = self._audio.currentTime + indice * 0.12;
          ganho.gain.setValueAtTime(0.0001, inicio);
          ganho.gain.exponentialRampToValueAtTime(0.25, inicio + 0.02);
          ganho.gain.exponentialRampToValueAtTime(0.0001, inicio + 0.18);
          oscilador.connect(ganho).connect(self._audio.destination);
          oscilador.start(inicio);
          oscilador.stop(inicio + 0.2);
        });
      } catch (erro) {
        console.warn('[Kronus] Falha ao tocar confirmacao:', erro);
      }
    },

    /**
     * Mensagem de sucesso personalizada.
     *
     * `{nome}` e `{hora}` são substituídos. O RH escreve "Bom trabalho,
     * {nome}!" e a tela mostra o nome de quem acabou de bater.
     */
    mensagemSucesso: function (nome, hora) {
      var modelo = (this.config && this.config.mensagem_sucesso) || 'Ponto registrado!';
      return modelo
        .replace(/\{nome\}/g, nome || '')
        .replace(/\{hora\}/g, hora || '')
        .trim();
    }
  };

  global.KronusPersonalizacao = Personalizacao;
})(window);
