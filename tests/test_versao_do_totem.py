"""
Kronus — saber se a atualizacao chegou ao totem.

A pergunta "todos os totens receberam a atualizacao?" nao tinha
resposta: dava para PEDIR a recarga e nao dava para CONFERIR se ela
aconteceu. O heartbeat so informava a versao fixa do app ("1.0"), que
nunca muda.

`recebeu_a_atualizacao` respondia outra coisa — se o totem entende
pedidos de recarga. Um totem pode entender o pedido e ainda assim estar
rodando codigo de tres deploys atras.
"""
from django.test import TestCase
from django.urls import reverse

from tests.test_totem import BaseTotemTestCase


class VersaoCarregadaTests(BaseTotemTestCase):
    def _bater(self, **extra):
        return self.client.post(
            reverse("api:totem:totem_heartbeat"),
            data={"versao": "1.0", **extra},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Token {self.totem.token_acesso}",
        )

    def test_o_totem_informa_qual_codigo_carregou(self):
        self._bater(estaticos="abc123")
        self.totem.refresh_from_db()
        self.assertEqual(self.totem.versao_estaticos, "abc123")

    def test_sem_informar_nao_apaga_o_que_ja_sabia(self):
        self.totem.versao_estaticos = "abc123"
        self.totem.save(update_fields=["versao_estaticos"])
        self._bater()
        self.totem.refresh_from_db()
        self.assertEqual(self.totem.versao_estaticos, "abc123")

    def test_atualizado_compara_com_o_servidor(self):
        from apps.core.versao import versao_dos_estaticos

        self.totem.versao_estaticos = versao_dos_estaticos()
        self.totem.save(update_fields=["versao_estaticos"])
        self.assertTrue(self.totem.esta_atualizado)

    def test_versao_antiga_aparece_como_desatualizado(self):
        self.totem.versao_estaticos = "versao-de-tres-deploys-atras"
        self.totem.save(update_fields=["versao_estaticos"])
        self.assertFalse(self.totem.esta_atualizado)

    def test_quem_nunca_informou_nao_conta_como_atualizado(self):
        """
        Silencio nao e confirmacao. Um totem que nunca mandou o campo
        pode estar rodando qualquer coisa — inclusive codigo que nem
        sabe informar.
        """
        self.totem.versao_estaticos = ""
        self.totem.save(update_fields=["versao_estaticos"])
        self.assertFalse(self.totem.esta_atualizado)

    def test_e_diferente_de_entender_o_pedido_de_recarga(self):
        """
        As duas propriedades respondem perguntas diferentes, e confundi-
        las foi o que me fez afirmar que os totens estavam atualizados
        quando eu so sabia que eles escutavam o pedido.
        """
        from apps.core.versao import versao_dos_estaticos

        self.totem.modo_exibicao = "fullscreen"
        self.totem.versao_estaticos = "antiga"
        self.totem.save(update_fields=["modo_exibicao", "versao_estaticos"])

        self.assertTrue(self.totem.recebeu_a_atualizacao)
        self.assertFalse(self.totem.esta_atualizado)
