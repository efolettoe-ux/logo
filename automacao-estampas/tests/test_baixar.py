"""baixar: servidor HTTP local (sem internet): baixa, retoma, tenta de novo, 404, largura no CDN, certificado."""
import http.server
import ssl
import sys
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import baixar as B  # noqa: E402
from catalogo import ImagemLoja, Produto  # noqa: E402

CONTEUDO = b"\x89PNG-fake-" + bytes(range(256)) * 50


class _Handler(http.server.BaseHTTPRequestHandler):
    pedidos = []
    falhas_restantes = {}

    def do_GET(self):  # noqa: N802
        _Handler.pedidos.append(self.path)
        caminho = self.path.split("?")[0]
        if caminho.endswith("nao-existe.png"):
            self.send_error(404)
            return
        if _Handler.falhas_restantes.get(caminho, 0) > 0:
            _Handler.falhas_restantes[caminho] -= 1
            self.send_error(503)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(CONTEUDO)))
        self.end_headers()
        self.wfile.write(CONTEUDO)

    def log_message(self, *a):
        pass


class TestBaixar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        _Handler.pedidos.clear()
        _Handler.falhas_restantes.clear()

    def test_largura_no_cdn(self):
        u = "https://cdn.shopify.com/s/files/1/0780/files/2_abc.png?v=1789007236"
        self.assertEqual(B.url_com_largura(u, 1500),
                         "https://cdn.shopify.com/s/files/1/0780/files/2_abc.png?v=1789007236&width=1500")
        self.assertEqual(B.url_com_largura(u + "&width=300", 1500).count("width="), 1)
        self.assertEqual(B.url_com_largura("http://outro.site/a.png", 1500), "http://outro.site/a.png")
        self.assertEqual(B.nome_arquivo(u), "2_abc.png")
        self.assertEqual(B.nome_arquivo("https://x/y/FRENTE%20PRETA.png?v=1"), "FRENTE PRETA.png")

    def test_baixa_retoma_e_erros(self):
        p = Produto("martini", "MARTINI T-SHIRT", "MARTINI", "T-Shirt", "active", "", ["Preta"])
        p.imagens = [ImagemLoja(f"{self.url}/f/1_a.png?v=1", 1), ImagemLoja(f"{self.url}/f/2_b.png?v=1", 2),
                     ImagemLoja(f"{self.url}/f/1_a.png?v=2", 3),  # repetida (outro ?v=) -> uma vez só
                     ImagemLoja(f"{self.url}/f/nao-existe.png", 4)]
        p.imagem_variante = {"Preta": f"{self.url}/f/2_b.png?v=1"}
        _Handler.falhas_restantes["/f/2_b.png"] = 2  # instável: 2 falhas e depois funciona
        with tempfile.TemporaryDirectory() as d:
            itens = B.itens_para_baixar([p], Path(d), 1500)
            self.assertEqual(len(itens), 3)
            self.assertEqual([i["cores_variante"] for i in itens], ["", "Preta", ""])
            res = {Path(r["arquivo"]).name: r for r in B.baixar_tudo(itens, workers=4, tentativas=4, espera_base=0.01)}
            self.assertEqual(res["1_a.png"]["status"], "ok")
            self.assertEqual(res["2_b.png"]["status"], "ok")
            self.assertEqual(res["nao-existe.png"]["status"], "erro")
            self.assertIn("404", res["nao-existe.png"]["observacao"])
            self.assertEqual((Path(d) / "martini" / "1_a.png").read_bytes(), CONTEUDO)
            self.assertFalse(list(Path(d).rglob("*.part")))
            # 404 não é tentado de novo
            self.assertEqual(sum(1 for x in _Handler.pedidos if "nao-existe" in x), 1)
            # segunda rodada: nada é baixado de novo
            _Handler.pedidos.clear()
            res = B.baixar_tudo(itens, workers=2, tentativas=1, espera_base=0.01)
            self.assertEqual(sorted(r["status"] for r in res), ["erro", "pulado", "pulado"])
            self.assertEqual(len(_Handler.pedidos), 1)

    def test_parcial_nao_conta_como_baixado(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "x" / "3_c.png"
            dest.parent.mkdir()
            (dest.parent / "3_c.png.part").write_bytes(b"pela metade")
            st, _ = B.baixar_um(f"{self.url}/f/3_c.png", dest, 1, 5, None, 0.01)
            self.assertEqual(st, "ok")
            self.assertEqual(dest.read_bytes(), CONTEUDO)

    def test_erro_de_certificado(self):
        e = urllib.error.URLError(ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"))
        self.assertTrue(B.eh_erro_certificado(e))
        self.assertIn("Install Certificates.command", B.AVISO_CERTIFICADO)
        self.assertIn("pip3 install certifi", B.AVISO_CERTIFICADO)


if __name__ == "__main__":
    unittest.main()
