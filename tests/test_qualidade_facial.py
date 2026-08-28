"""
Kronus — degradacao do reconhecimento facial.

A degradacao e silenciosa: enquanto a distancia entre o rosto do dia e o
vetor guardado fica abaixo do limiar, o ponto e registrado normalmente e
ninguem percebe nada. O primeiro sinal costuma ser a pessoa reclamando na
fila do totem — e ai ja e um problema de gente, nao de sistema.
"""
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from apps.clientes.models import Cliente, Empresa
from apps.facial import qualidade
from apps.facial.models import TentativaReconhecimento
from apps.master.models import Plano
from apps.rh.models import Colaborador


class QualidadeFacialTests(TestCase):
    def setUp(self):
        plano = Plano.objects.create(nome="P", slug="p", max_colaboradores=99)
        cliente = Cliente.objects.create(
            razao_social="Alfa", cnpj="45997418000153",
            plano=plano, email_contato="a@x.com",
        )
        self.empresa = Empresa.objects.create(
            cliente=cliente, razao_social="Alfa", cnpj="45997418000234",
        )
        self.limiar = qualidade.limiar()

    def _colab(self, nome, cpf):
        return Colaborador.objects.create(
            empresa=self.empresa, cpf=cpf, nome_completo=nome,
            data_nascimento=date(1990, 1, 1), data_admissao=date(2024, 1, 1),
        )

    def _tentativas(self, colaborador, distancia, quantas):
        for _ in range(quantas):
            TentativaReconhecimento.objects.create(
                empresa=self.empresa, colaborador=colaborador,
                resultado=TentativaReconhecimento.Resultado.IDENTIFICADO,
                distancia=distancia,
            )

    def test_rosto_bem_reconhecido_fica_como_boa(self):
        c = self._colab("Ana", "52998224725")
        self._tentativas(c, self.limiar * 0.4, 10)

        item = qualidade.avaliar(self.empresa)[0]
        self.assertEqual(item["situacao"], qualidade.Situacao.BOA)

    def test_margem_estreita_vira_atencao(self):
        c = self._colab("Bruno", "11144477735")
        self._tentativas(c, self.limiar * 0.83, 10)

        item = qualidade.avaliar(self.empresa)[0]
        self.assertEqual(item["situacao"], qualidade.Situacao.ATENCAO)

    def test_quase_no_limiar_vira_critica(self):
        c = self._colab("Carla", "34608514300")
        self._tentativas(c, self.limiar * 0.95, 10)

        item = qualidade.avaliar(self.empresa)[0]
        self.assertEqual(item["situacao"], qualidade.Situacao.CRITICA)
        self.assertGreaterEqual(item["folga_consumida"], 90)

    def test_amostra_pequena_e_ignorada(self):
        """
        Duas ou tres identificacoes dizem mais sobre a iluminacao do dia
        do que sobre o cadastro.
        """
        c = self._colab("Diego", "40364873882")
        self._tentativas(c, self.limiar * 0.95, 3)

        self.assertEqual(qualidade.avaliar(self.empresa), [])

    def test_tentativas_antigas_nao_contam(self):
        c = self._colab("Elisa", "24971563792")
        self._tentativas(c, self.limiar * 0.95, 10)
        antigo = timezone.now() - timedelta(days=qualidade.DIAS_OBSERVADOS + 5)
        TentativaReconhecimento.objects.update(created_at=antigo)

        self.assertEqual(qualidade.avaliar(self.empresa), [])

    def test_falhas_nao_entram_na_media(self):
        """Uma falha nao tem distancia confiavel para comparar."""
        c = self._colab("Fabio", "94759556362")
        self._tentativas(c, self.limiar * 0.4, 10)
        for _ in range(10):
            TentativaReconhecimento.objects.create(
                empresa=self.empresa, colaborador=c,
                resultado=TentativaReconhecimento.Resultado.NAO_IDENTIFICADO,
                distancia=0.99,
            )

        item = qualidade.avaliar(self.empresa)[0]
        self.assertEqual(item["situacao"], qualidade.Situacao.BOA)

    def test_ordena_do_pior_para_o_melhor(self):
        bom = self._colab("Bom", "52998224725")
        ruim = self._colab("Ruim", "11144477735")
        self._tentativas(bom, self.limiar * 0.3, 10)
        self._tentativas(ruim, self.limiar * 0.95, 10)

        nomes = [i["nome"] for i in qualidade.avaliar(self.empresa)]
        self.assertEqual(nomes, ["Ruim", "Bom"])

    def test_em_risco_traz_so_quem_precisa_de_acao(self):
        bom = self._colab("Bom", "52998224725")
        ruim = self._colab("Ruim", "11144477735")
        self._tentativas(bom, self.limiar * 0.3, 10)
        self._tentativas(ruim, self.limiar * 0.95, 10)

        self.assertEqual([i["nome"] for i in qualidade.em_risco(self.empresa)], ["Ruim"])

    def test_os_cortes_acompanham_o_limiar(self):
        """
        Cortes fixos ficariam errados em silencio se alguem mexesse no
        limiar — e o alerta pararia de alertar sem ninguem notar.
        """
        self.assertEqual(
            qualidade.classificar(0.5, corte=1.0), qualidade.Situacao.BOA
        )
        self.assertEqual(
            qualidade.classificar(0.85, corte=1.0), qualidade.Situacao.ATENCAO
        )
        self.assertEqual(
            qualidade.classificar(0.95, corte=1.0), qualidade.Situacao.CRITICA
        )

    def test_a_task_avisa_o_gestor(self):
        from apps.accounts.models import CustomUser
        from apps.core.constants import TipoUsuario
        from apps.facial.tasks import monitorar_qualidade_facial
        from apps.notificacoes.models import Notificacao

        gestor = CustomUser.objects.create_user(
            email="rh@alfa.com", password="x", nome_completo="RH",
            tipo=TipoUsuario.RH, cliente=self.empresa.cliente,
        )
        gestor.empresas.add(self.empresa)

        c = self._colab("Gabriel", "52998224725")
        self._tentativas(c, self.limiar * 0.95, 10)

        resultado = monitorar_qualidade_facial()
        self.assertEqual(resultado["colaboradores"], 1)
        self.assertTrue(
            Notificacao.objects.filter(
                destinatario=gestor,
                evento=Notificacao.Evento.FACIAL_DEGRADADO,
            ).exists()
        )

    def test_a_task_nao_avisa_quando_esta_tudo_bem(self):
        from apps.facial.tasks import monitorar_qualidade_facial
        from apps.notificacoes.models import Notificacao

        c = self._colab("Helena", "52998224725")
        self._tentativas(c, self.limiar * 0.3, 10)

        monitorar_qualidade_facial()
        self.assertFalse(Notificacao.objects.exists())
