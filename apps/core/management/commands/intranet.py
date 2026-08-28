"""
Kronus — sobe o servidor de desenvolvimento acessível na rede local.

    python manage.py intranet            # HTTPS (câmera funciona)
    python manage.py intranet --http     # HTTP simples (câmera bloqueada)
    python manage.py intranet --porta 9000

**Por que HTTPS em desenvolvimento?** `getUserMedia` — a API que dá
acesso à câmera — só funciona em *contexto seguro*. O navegador libera
`localhost` por exceção, mas bloqueia qualquer `http://` em outro
endereço. Sem TLS, o totem abre no tablet e a câmera simplesmente não
liga. Por isso o padrão aqui é HTTPS com certificado autoassinado,
gerado na hora e incluindo o IP da máquina no SAN.

O certificado é autoassinado: o navegador vai avisar. É esperado — o
comando explica como prosseguir.
"""
import datetime
import ipaddress
import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core.utils import detectar_ip_lan, ips_locais

PASTA_CERT = Path(settings.BASE_DIR) / ".certs"
ARQ_CERT = PASTA_CERT / "kronus-dev.crt"
ARQ_CHAVE = PASTA_CERT / "kronus-dev.key"


class Command(BaseCommand):
    help = "Sobe o servidor acessível na rede local, com HTTPS para o totem."

    def add_arguments(self, parser):
        parser.add_argument("--porta", type=int, default=None, help="Porta (padrão: 8443 HTTPS / 8000 HTTP).")
        parser.add_argument("--http", action="store_true", help="Servir em HTTP simples (a câmera não funcionará).")
        parser.add_argument("--ip", default=None, help="Força um IP em vez de detectar.")
        parser.add_argument("--recriar-cert", action="store_true", help="Regenera o certificado.")

    def handle(self, *args, **opcoes):
        ip = opcoes["ip"] or detectar_ip_lan()
        if not ip:
            raise CommandError(
                "Não foi possível detectar o IP da rede local. "
                "Verifique a conexão ou informe com --ip."
            )

        usar_https = not opcoes["http"]
        porta = opcoes["porta"] or (8443 if usar_https else 8000)
        esquema = "https" if usar_https else "http"
        base = f"{esquema}://{ip}:{porta}"

        self._cabecalho(ip, base, usar_https)
        self._listar_totens(base)

        if usar_https:
            self._garantir_certificado(ip, recriar=opcoes["recriar_cert"])
            self._avisos_https()
            comando = [
                sys.executable, "manage.py", "runserver_plus",
                f"0.0.0.0:{porta}",
                "--cert-file", str(ARQ_CERT),
                "--key-file", str(ARQ_CHAVE),
            ]
        else:
            self._avisos_http(base)
            comando = [sys.executable, "manage.py", "runserver", f"0.0.0.0:{porta}"]

        self.stdout.write(self.style.MIGRATE_HEADING("\nIniciando o servidor... (Ctrl+C para parar)\n"))
        try:
            subprocess.run(comando, cwd=str(settings.BASE_DIR))
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nServidor encerrado."))

    # ══════════════════════════════════════════════════════════
    # Saída
    # ══════════════════════════════════════════════════════════
    def _cabecalho(self, ip, base, https):
        self.stdout.write(self.style.MIGRATE_HEADING("\nKronus - intranet de testes"))
        self.stdout.write(f"  IP detectado ....... {ip}")
        outros = [i for i in ips_locais() if i != ip]
        if outros:
            self.stdout.write(f"  Outras interfaces .. {', '.join(outros)}")
        self.stdout.write(f"  Modo ............... {'HTTPS (camera habilitada)' if https else 'HTTP (camera BLOQUEADA)'}")
        self.stdout.write(f"\n  Painel ............. {base}/")
        self.stdout.write(f"  Login .............. {base}/accounts/login/")
        self.stdout.write(f"  API docs ........... {base}/api/v1/docs/")

    def _listar_totens(self, base):
        """Imprime a URL de cada totem cadastrado — é o que se digita no tablet."""
        try:
            from apps.totem.models import Totem

            totens = Totem.objects.filter(ativo=True).select_related("empresa")[:10]
        except Exception:
            return

        if not totens:
            self.stdout.write(self.style.WARNING("\n  Nenhum totem ativo cadastrado."))
            self.stdout.write("  Rode `python scripts/seed_data.py` para criar dados de teste.")
            return

        self.stdout.write(self.style.MIGRATE_HEADING("\n  Totens (abra esta URL no tablet):"))
        for totem in totens:
            self.stdout.write(f"    {totem.identificador} - {totem.empresa.nome_exibicao}")
            self.stdout.write(self.style.SUCCESS(f"      {base}/totem/{totem.token_acesso}/"))
            self.stdout.write(f"      diagnostico: {base}/totem/{totem.token_acesso}/diagnostico/")

    def _avisos_https(self):
        self.stdout.write(self.style.MIGRATE_HEADING("\n  Certificado autoassinado"))
        self.stdout.write("  O navegador vai alertar que a conexao nao e privada. E esperado:")
        self.stdout.write("    Chrome/Android : 'Avancado' > 'Ir para <ip> (nao seguro)'")
        self.stdout.write("    Ou digite 'thisisunsafe' com a pagina de aviso em foco.")
        self.stdout.write("  Depois de aceito uma vez, a camera funciona normalmente.")

    def _avisos_http(self, base):
        self.stdout.write(self.style.ERROR("\n  ATENCAO: em HTTP a camera do totem NAO vai funcionar."))
        self.stdout.write("  `getUserMedia` exige contexto seguro fora de localhost.")
        self.stdout.write("  Alternativas:")
        self.stdout.write("    1. use o modo HTTPS (padrao deste comando)")
        self.stdout.write("    2. no Chrome do tablet, abra chrome://flags e adicione")
        self.stdout.write(f"       '{base}' em 'Insecure origins treated as secure'")
        self.stdout.write("  O fallback por CPF do totem funciona em HTTP normalmente.")

    # ══════════════════════════════════════════════════════════
    # Certificado
    # ══════════════════════════════════════════════════════════
    def _garantir_certificado(self, ip, recriar=False):
        """
        Gera um certificado autoassinado válido para este IP.

        O IP entra no **SAN** (Subject Alternative Name); navegadores
        modernos ignoram o Common Name e só olham o SAN. Sem isso o
        certificado é recusado mesmo depois de aceito manualmente.
        """
        PASTA_CERT.mkdir(exist_ok=True)

        if ARQ_CERT.exists() and not recriar and self._cert_cobre_ip(ip):
            self.stdout.write(f"\n  Certificado ........ {ARQ_CERT.name} (valido para {ip})")
            return

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        self.stdout.write(f"\n  Gerando certificado para {ip}...")

        chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        nome = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "BR"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "KS TEC - Kronus (desenvolvimento)"),
            x509.NameAttribute(NameOID.COMMON_NAME, ip),
        ])

        alternativos = [x509.DNSName("localhost")]
        for endereco in {ip, "127.0.0.1", *ips_locais()}:
            try:
                alternativos.append(x509.IPAddress(ipaddress.ip_address(endereco)))
            except ValueError:
                continue

        agora = datetime.datetime.now(datetime.timezone.utc)
        certificado = (
            x509.CertificateBuilder()
            .subject_name(nome)
            .issuer_name(nome)
            .public_key(chave.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(agora - datetime.timedelta(days=1))
            .not_valid_after(agora + datetime.timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName(alternativos), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(chave, hashes.SHA256())
        )

        ARQ_CERT.write_bytes(certificado.public_bytes(serialization.Encoding.PEM))
        ARQ_CHAVE.write_bytes(
            chave.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        # A chave privada não deve ficar legível para outros usuários.
        try:
            os.chmod(ARQ_CHAVE, 0o600)
        except OSError:
            pass

        self.stdout.write(self.style.SUCCESS(f"  Certificado criado: {ARQ_CERT} (valido por 365 dias)"))

    @staticmethod
    def _cert_cobre_ip(ip) -> bool:
        """O certificado existente já vale para o IP atual?"""
        try:
            from cryptography import x509

            cert = x509.load_pem_x509_certificate(ARQ_CERT.read_bytes())
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            return ipaddress.ip_address(ip) in san.get_values_for_type(x509.IPAddress)
        except Exception:
            return False
