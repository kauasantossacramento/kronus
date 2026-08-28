/**
 * Kronus — componente Alpine de captura de foto.
 *
 * Duas entradas para o mesmo campo: câmera ou arquivo. O resultado da
 * câmera vira um `File` real, injetado no `<input type="file">` original
 * via DataTransfer — assim o formulário Django recebe um upload comum,
 * sem endpoint novo, sem base64 no POST e sem tratamento especial no
 * backend.
 *
 * Usado no cadastro do colaborador (foto de perfil) e disponível para
 * qualquer outro campo de imagem.
 */
function capturaFoto(idCampo) {
  return {
    input: null,
    stream: null,
    camaraAberta: false,
    temImagem: false,
    erro: '',
    motivoSemCamera: '',
    podeUsarCamera: false,

    /** Lado maior da imagem gravada — suficiente para foto de perfil. */
    LADO: 720,

    init() {
      this.input = document.getElementById(idCampo);
      this.temImagem = Boolean(this.$refs.preview && this.$refs.preview.getAttribute('src'));

      // Arquivo escolhido pelo seletor nativo: só atualiza o preview.
      if (this.input) {
        this.$refs.arquivo = this.input;
        this.input.addEventListener('change', () => this.previewDoInput());
      }

      this.avaliarSuporteDeCamera();
    },

    /**
     * A câmera exige contexto seguro. Em vez de oferecer um botão que
     * falha, detectamos antes e explicamos o motivo — o usuário sabe
     * que precisa de HTTPS, não que o sistema está quebrado.
     */
    avaliarSuporteDeCamera() {
      if (!window.isSecureContext) {
        this.podeUsarCamera = false;
        this.motivoSemCamera =
          'A câmera exige conexão segura (HTTPS). Neste endereço, use "Escolher arquivo". ' +
          'Para habilitar, rode o servidor com: manage.py intranet';
        return;
      }
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        this.podeUsarCamera = false;
        this.motivoSemCamera = 'Este navegador não expõe acesso à câmera.';
        return;
      }
      this.podeUsarCamera = true;
      this.motivoSemCamera = '';
    },

    abrirCamera() {
      this.erro = '';
      navigator.mediaDevices
        .getUserMedia({
          video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 960 } },
          audio: false
        })
        .then((stream) => {
          this.stream = stream;
          this.camaraAberta = true;
          // O elemento só existe depois do x-show; esperamos o Alpine pintar.
          this.$nextTick(() => {
            this.$refs.video.srcObject = stream;
          });
        })
        .catch((e) => {
          this.erro =
            e.name === 'NotAllowedError'
              ? 'Permissão de câmera negada. Libere o acesso nas configurações do navegador.'
              : e.name === 'NotFoundError'
              ? 'Nenhuma câmera encontrada neste dispositivo.'
              : 'Não foi possível acessar a câmera.';
        });
    },

    fecharCamera() {
      if (this.stream) {
        this.stream.getTracks().forEach((t) => t.stop());
        this.stream = null;
      }
      this.camaraAberta = false;
    },

    tirarFoto() {
      const video = this.$refs.video;
      if (!video || video.readyState < 2) return;

      // Recorta o quadrado central: foto de perfil é exibida circular,
      // e enquadrar aqui evita distorção depois.
      const lado = Math.min(video.videoWidth, video.videoHeight);
      const sx = (video.videoWidth - lado) / 2;
      const sy = (video.videoHeight - lado) / 2;

      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = this.LADO;
      const ctx = canvas.getContext('2d');
      // Desespelha: o preview é espelhado para o usuário se orientar,
      // mas a foto gravada precisa sair na orientação real.
      ctx.translate(this.LADO, 0);
      ctx.scale(-1, 1);
      ctx.drawImage(video, sx, sy, lado, lado, 0, 0, this.LADO, this.LADO);

      canvas.toBlob(
        (blob) => {
          if (!blob) {
            this.erro = 'Falha ao processar a imagem.';
            return;
          }
          const arquivo = new File([blob], `foto_${Date.now()}.jpg`, {
            type: 'image/jpeg',
            lastModified: Date.now()
          });
          this.aplicarArquivo(arquivo);
          this.fecharCamera();
        },
        'image/jpeg',
        0.9
      );
    },

    /** Injeta o File no input original — o form envia como upload normal. */
    aplicarArquivo(arquivo) {
      if (!this.input) return;
      const dt = new DataTransfer();
      dt.items.add(arquivo);
      this.input.files = dt.files;
      this.input.dispatchEvent(new Event('change', { bubbles: true }));
      this.mostrarPreview(arquivo);
    },

    previewDoInput() {
      const arquivo = this.input && this.input.files && this.input.files[0];
      if (arquivo) this.mostrarPreview(arquivo);
    },

    mostrarPreview(arquivo) {
      const leitor = new FileReader();
      leitor.onload = (e) => {
        this.$refs.preview.src = e.target.result;
        this.temImagem = true;
      };
      leitor.readAsDataURL(arquivo);
    },

    limpar() {
      if (this.input) {
        this.input.value = '';
        this.input.dispatchEvent(new Event('change', { bubbles: true }));
      }
      this.$refs.preview.removeAttribute('src');
      this.temImagem = false;
    },

    destroy() {
      this.fecharCamera();
    }
  };
}
