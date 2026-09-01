"""
Kronus — busca de imagens para a tela ociosa.

Os termos sao curados, e nao genericos: buscar "manha" devolve
despertador, transito e gente correndo — o oposto do que uma tela de
recepcao deve transmitir as 7h.
"""
from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.clientes import pexels


class TermosTests(TestCase):
    def test_os_tres_periodos_tem_termos(self):
        for periodo in ("manha", "tarde", "noite"):
            self.assertTrue(pexels.TERMOS.get(periodo), periodo)

    def test_varios_termos_por_periodo(self):
        """
        Um termo unico devolveria sempre as mesmas fotos, e o rodizio
        ficaria obvio na primeira semana.
        """
        for periodo, termos in pexels.TERMOS.items():
            self.assertGreaterEqual(len(termos), 4, periodo)

    def test_a_noite_pede_imagem_escura(self):
        """
        O periodo da noite existe para transmitir descanso. Foto clara
        ali quebra a intencao — e a busca e o unico lugar onde da para
        pedir isso.
        """
        termos = " ".join(pexels.TERMOS["noite"]).lower()
        self.assertTrue(
            any(p in termos for p in ("night", "moon", "star", "dark"))
        )

    def test_a_manha_pede_luz(self):
        termos = " ".join(pexels.TERMOS["manha"]).lower()
        self.assertTrue(
            any(p in termos for p in ("sunrise", "morning", "light", "golden"))
        )


class BuscaTests(TestCase):
    @override_settings(PEXELS_API_KEY="")
    def test_sem_chave_nao_busca_e_nao_quebra(self):
        """
        Chave ausente desliga o recurso — nao derruba nada. O acervo
        continua com o que ja foi importado.
        """
        self.assertEqual(pexels.buscar("manha"), [])

    @override_settings(PEXELS_API_KEY="chave")
    def test_descarta_imagem_pequena(self):
        """
        A imagem fica atras da logo e do relogio numa tela grande.
        Resolucao baixa ali aparece como borrao.
        """
        resposta = _resposta({
            "photos": [
                {"id": 1, "width": 800, "src": {"large2x": "u"},
                 "photographer": "A", "url": "p", "alt": "pequena"},
                {"id": 2, "width": 4000, "src": {"large2x": "u2"},
                 "photographer": "B", "url": "p2", "alt": "grande"},
            ]
        })
        with patch.object(pexels, "_requests", return_value=_Fake(resposta)):
            achadas = pexels.buscar("manha")
        self.assertTrue(all(a["id_externo"] != "1" for a in achadas))
        self.assertTrue(any(a["id_externo"] == "2" for a in achadas))

    @override_settings(PEXELS_API_KEY="chave")
    def test_nao_repete_a_mesma_foto_entre_termos(self):
        """
        Termos parecidos devolvem a mesma foto. Sem deduplicar, ela
        entraria varias vezes e a tela repetiria mais, nao menos.
        """
        resposta = _resposta({
            "photos": [
                {"id": 7, "width": 4000, "src": {"large2x": "u"},
                 "photographer": "A", "url": "p", "alt": "repetida"},
            ]
        })
        with patch.object(pexels, "_requests", return_value=_Fake(resposta)):
            achadas = pexels.buscar("manha")
        self.assertEqual(len(achadas), 1)

    @override_settings(PEXELS_API_KEY="chave")
    def test_um_termo_que_falha_nao_derruba_os_outros(self):
        """
        Seis termos por periodo: se um erro na rede zerasse a busca
        inteira, o acervo dependeria de todos darem certo ao mesmo
        tempo.
        """
        class MeioQuebrado:
            def __init__(self):
                self.chamadas = 0

            def get(self, *a, **kw):
                self.chamadas += 1
                if self.chamadas == 1:
                    raise RuntimeError("rede caiu")
                return _resposta({
                    "photos": [{
                        "id": self.chamadas, "width": 4000,
                        "src": {"large2x": "u"}, "photographer": "A",
                        "url": "p", "alt": "ok",
                    }]
                })

        with patch.object(pexels, "_requests", return_value=MeioQuebrado()):
            achadas = pexels.buscar("manha")
        self.assertTrue(achadas)

    @override_settings(PEXELS_API_KEY="chave")
    def test_guarda_a_procedencia_mesmo_sem_exibir(self):
        """
        A licenca do Pexels dispensa credito, e o totem nao mostra. Mas
        um ano depois "de onde veio esta foto?" precisa ter resposta.
        """
        resposta = _resposta({
            "photos": [{
                "id": 9, "width": 4000, "src": {"large2x": "arquivo"},
                "photographer": "Fulano", "url": "https://pexels.test/9",
                "alt": "titulo",
            }]
        })
        with patch.object(pexels, "_requests", return_value=_Fake(resposta)):
            achada = pexels.buscar("manha")[0]
        self.assertEqual(achada["autor"], "Fulano")
        self.assertEqual(achada["fonte"], "https://pexels.test/9")


class DownloadTests(TestCase):
    def test_falha_ao_baixar_devolve_none(self):
        class Quebrado:
            def get(self, *a, **kw):
                raise RuntimeError("404")

        with patch.object(pexels, "_requests", return_value=Quebrado()):
            self.assertIsNone(pexels.baixar("u"))


# -- ajudantes -------------------------------------------------
def _resposta(json_):
    class Resposta:
        def raise_for_status(self):
            return None

        def json(self):
            return json_

    return Resposta()


class _Fake:
    def __init__(self, resposta):
        self._resposta = resposta

    def get(self, *a, **kw):
        return self._resposta
