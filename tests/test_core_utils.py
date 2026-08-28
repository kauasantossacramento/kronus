"""Kronus — testes dos utilitarios de dominio (Fase 1)."""
from datetime import datetime, timezone as dt_timezone

from django.test import SimpleTestCase, override_settings

from apps.core import utils


class CPFTests(SimpleTestCase):
    def test_aceita_cpf_valido_com_e_sem_mascara(self):
        self.assertTrue(utils.cpf_valido("529.982.247-25"))
        self.assertTrue(utils.cpf_valido("52998224725"))

    def test_recusa_digito_verificador_errado(self):
        self.assertFalse(utils.cpf_valido("52998224726"))

    def test_recusa_sequencias_repetidas(self):
        for digito in range(10):
            self.assertFalse(utils.cpf_valido(str(digito) * 11))

    def test_recusa_tamanho_invalido(self):
        self.assertFalse(utils.cpf_valido("1234567890"))
        self.assertFalse(utils.cpf_valido(""))

    def test_formatacao(self):
        self.assertEqual(utils.formatar_cpf("52998224725"), "529.982.247-25")

    def test_mascaramento_oculta_os_tres_primeiros_digitos(self):
        self.assertEqual(utils.mascarar_cpf("52998224725"), "***.982.247-25")


class CNPJTests(SimpleTestCase):
    def test_aceita_cnpj_valido(self):
        self.assertTrue(utils.cnpj_valido("11.222.333/0001-81"))

    def test_recusa_cnpj_invalido(self):
        self.assertFalse(utils.cnpj_valido("11222333000182"))
        self.assertFalse(utils.cnpj_valido("11111111111111"))

    def test_formatacao(self):
        self.assertEqual(utils.formatar_cnpj("11222333000181"), "11.222.333/0001-81")


class PISTests(SimpleTestCase):
    def test_valida_pis(self):
        self.assertTrue(utils.pis_valido("12056412545"))
        self.assertFalse(utils.pis_valido("12056412546"))


@override_settings(HASH_SALT_GLOBAL="salt-de-teste")
class HashRegistroTests(SimpleTestCase):
    """Integridade encadeada exigida pela Portaria 671 (regra 3, Seção 14)."""

    def _hash(self, nsr=1, anterior=""):
        return utils.gerar_hash_registro(
            colaborador_id=7,
            data_hora=datetime(2026, 8, 27, 8, 2, 15, tzinfo=dt_timezone.utc),
            nsr=nsr,
            salt_empresa="salt-empresa",
            hash_anterior=anterior,
        )

    def test_hash_e_deterministico(self):
        self.assertEqual(self._hash(), self._hash())

    def test_hash_tem_64_hex(self):
        valor = self._hash()
        self.assertEqual(len(valor), 64)
        int(valor, 16)  # levanta ValueError se não for hexadecimal

    def test_nsr_diferente_produz_hash_diferente(self):
        self.assertNotEqual(self._hash(nsr=1), self._hash(nsr=2))

    def test_encadeamento_altera_o_hash(self):
        """Alterar o registro anterior invalida todos os subsequentes."""
        self.assertNotEqual(self._hash(anterior=""), self._hash(anterior="abc"))

    def test_codigo_curto_e_legivel(self):
        self.assertRegex(utils.hash_curto(self._hash()), r"^[0-9A-F]{4}(-[0-9A-F]{4}){3}$")


class GeolocalizacaoTests(SimpleTestCase):
    """Haversine para geofencing (Seção 8.3)."""

    def test_distancia_para_o_mesmo_ponto_e_zero(self):
        self.assertAlmostEqual(
            utils.distancia_haversine(-13.3705, -39.0733, -13.3705, -39.0733), 0, places=3
        )

    def test_distancia_conhecida_valenca_salvador(self):
        # Valença/BA → Salvador/BA: ~76 km em linha reta.
        metros = utils.distancia_haversine(-13.3705, -39.0733, -12.9777, -38.5016)
        self.assertGreater(metros, 70_000)
        self.assertLess(metros, 82_000)

    def test_dentro_do_raio(self):
        self.assertTrue(utils.dentro_do_raio(-13.3705, -39.0733, -13.3706, -39.0734, 200))
        self.assertFalse(utils.dentro_do_raio(-13.3705, -39.0733, -12.9777, -38.5016, 200))


class TempoTests(SimpleTestCase):
    def test_minutos_para_hhmm_positivo(self):
        self.assertEqual(utils.minutos_para_hhmm(510), "+08:30")

    def test_minutos_para_hhmm_negativo(self):
        self.assertEqual(utils.minutos_para_hhmm(-75), "-01:15")

    def test_minutos_para_hhmm_sem_sinal(self):
        self.assertEqual(utils.minutos_para_hhmm(510, com_sinal=False), "08:30")

    def test_ida_e_volta(self):
        for minutos in (0, 45, 510, -75, 1439):
            self.assertEqual(
                utils.hhmm_para_minutos(utils.minutos_para_hhmm(minutos)), minutos
            )


class HashDeRegistroTests(SimpleTestCase):
    """
    O hash de integridade tem que ser funcao do **instante**, nao da
    representacao do instante.

    Estes testes existem por causa de um defeito real encontrado na
    Fase 5: `gerar_hash_registro` serializava `data_hora.isoformat()`
    direto, entao o mesmo instante produzia hashes diferentes conforme
    o offset do datetime recebido. Quem grava passa horario local
    (`-03:00`); o banco devolve UTC. O resultado era uma verificacao de
    integridade que reprovava registros legitimos — o oposto do que a
    Portaria 671 espera dela.
    """

    BASE = dict(colaborador_id=7, nsr=42, salt_empresa="sal-da-empresa")

    def test_mesmo_instante_em_fusos_diferentes_da_o_mesmo_hash(self):
        from datetime import timedelta

        utc = datetime(2026, 8, 17, 11, 0, tzinfo=dt_timezone.utc)
        brasilia = utc.astimezone(dt_timezone(timedelta(hours=-3)))
        tokyo = utc.astimezone(dt_timezone(timedelta(hours=9)))

        # Tres representacoes, um unico instante.
        self.assertNotEqual(utc.isoformat(), brasilia.isoformat())
        self.assertEqual(
            utils.gerar_hash_registro(data_hora=utc, **self.BASE),
            utils.gerar_hash_registro(data_hora=brasilia, **self.BASE),
        )
        self.assertEqual(
            utils.gerar_hash_registro(data_hora=utc, **self.BASE),
            utils.gerar_hash_registro(data_hora=tokyo, **self.BASE),
        )

    def test_instantes_diferentes_dao_hashes_diferentes(self):
        """A normalizacao nao pode achatar horarios de verdade distintos."""
        um = datetime(2026, 8, 17, 11, 0, tzinfo=dt_timezone.utc)
        outro = datetime(2026, 8, 17, 11, 1, tzinfo=dt_timezone.utc)
        self.assertNotEqual(
            utils.gerar_hash_registro(data_hora=um, **self.BASE),
            utils.gerar_hash_registro(data_hora=outro, **self.BASE),
        )

    def test_encadeamento_muda_o_hash(self):
        momento = datetime(2026, 8, 17, 11, 0, tzinfo=dt_timezone.utc)
        sozinho = utils.gerar_hash_registro(data_hora=momento, **self.BASE)
        encadeado = utils.gerar_hash_registro(
            data_hora=momento, hash_anterior="a" * 64, **self.BASE
        )
        self.assertNotEqual(sozinho, encadeado)

    def test_salt_da_empresa_isola_as_cadeias(self):
        """Duas empresas com os mesmos dados nao produzem o mesmo hash."""
        momento = datetime(2026, 8, 17, 11, 0, tzinfo=dt_timezone.utc)
        uma = utils.gerar_hash_registro(
            colaborador_id=7, nsr=42, salt_empresa="empresa-a", data_hora=momento
        )
        outra = utils.gerar_hash_registro(
            colaborador_id=7, nsr=42, salt_empresa="empresa-b", data_hora=momento
        )
        self.assertNotEqual(uma, outra)
