"""Mockups, compositor e o comando estampar com um projeto sintético completo."""
import csv
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import estampar as E  # noqa: E402
import sintetico  # noqa: E402
from catalogo import CONFIG_PADRAO, LinhaMapa, Projeto, carregar_config, escrever_mapa, ler_mapa  # noqa: E402
from compositor import aplicar_estampa, enquadrar, preparar_mockup  # noqa: E402
from mockups import _pistas_mockup, descobrir_mockups, registrar_close  # noqa: E402

CFG = CONFIG_PADRAO


def criar_mockups(pasta: Path, cores=(("preta", (18, 18, 20)), ("branca", (244, 244, 244))), close=True, chumbo=True):
    pasta.mkdir(parents=True, exist_ok=True)
    for nome, rgb in cores:
        costas = sintetico.mockup_liso(300, 400, rgb, seed=2)
        costas.save(pasta / f"{nome}-costas.png")
        sintetico.mockup_liso(300, 400, rgb, seed=3).save(pasta / f"{nome}-frente.png")
        if close:
            # close = ampliação 2x da parte de cima das costas
            costas.crop((60, 60, 240, 300)).resize((360, 480), Image.LANCZOS).save(pasta / f"{nome}-close-costas.png")
    if chumbo:
        sintetico.mockup_liso(300, 400, (50, 50, 52)).save(pasta / "chumbo-costas.png")


class TestMockups(unittest.TestCase):
    def test_nomes(self):
        self.assertEqual(_pistas_mockup("azul-marinho-close-costas.png", CFG), ("Azul Marinho", "close-costas"))
        self.assertEqual(_pistas_mockup("off-white-frente.png", CFG), ("Off White", "frente"))
        self.assertEqual(_pistas_mockup("preta-costas.png", CFG), ("Preta", "costas"))
        self.assertEqual(_pistas_mockup("BRANCA FRENTE.PNG", CFG), ("Branca", "frente"))

    def test_descoberta_e_chumbo_desativado(self):
        with tempfile.TemporaryDirectory() as d:
            criar_mockups(Path(d))
            (Path(d) / ".DS_Store").write_text("x")
            r = descobrir_mockups(Path(d), CFG)
            self.assertEqual(len(r.mockups), 6)
            self.assertEqual(r.cores_completas(), {"Preta", "Branca"})
            self.assertEqual(r.cores_desativadas, ["Chumbo"])

    def test_registro_close(self):
        costas = sintetico.mockup_liso(600, 800, (230, 230, 232))
        # marcas para o alinhamento ter o que achar
        a = np.asarray(costas).copy()
        a[300:320, 250:270, :3] = 40
        a[380:390, 330:380, :3] = 90
        costas = Image.fromarray(a, "RGBA")
        x0, y0, esc = 120, 110, 1.8
        close = costas.crop((x0, y0, x0 + 360, y0 + 480)).resize((int(360 * esc), int(480 * esc)), Image.LANCZOS)
        reg = registrar_close(costas, close)
        self.assertAlmostEqual(reg.escala, esc, delta=0.03)
        self.assertAlmostEqual(reg.tx, x0, delta=3)
        self.assertAlmostEqual(reg.ty, y0, delta=3)


class TestCompositor(unittest.TestCase):
    def test_fora_da_estampa_igual_ao_mockup(self):
        mk_im = sintetico.mockup_liso(300, 400, (18, 18, 20))
        mk = preparar_mockup(mk_im, CFG)
        art = sintetico.estampa(80, 100)
        out = np.asarray(aplicar_estampa(mk, art, (110, 140, 80, 100), CFG))
        orig = np.asarray(mk_im)
        fora = np.ones(orig.shape[:2], bool)
        fora[130:250, 100:200] = False  # caixa + margem do deslocamento/borda
        self.assertTrue(np.array_equal(out[fora], orig[fora]))
        self.assertFalse(np.array_equal(out[~fora], orig[~fora]))
        # tinta vermelha aparece no meio da arte, sem virar cinza
        px = out[150, 120, :3].astype(int)
        self.assertGreater(px[0], px[1] + 60)

    def test_preto_em_camiseta_branca_fica_preto(self):
        mk = preparar_mockup(sintetico.mockup_liso(300, 400, (244, 244, 244)), CFG)
        art = Image.new("RGBA", (60, 60), (0, 0, 0, 255))
        out = np.asarray(aplicar_estampa(mk, art, (120, 160, 60, 60), CFG))
        self.assertLess(int(out[190, 150, :3].mean()), 45)

    def test_enquadramento_padrao_da_loja(self):
        im = sintetico.mockup_liso(300, 400)
        final, master = enquadrar(im, CFG, 400)
        self.assertEqual(final.size, (400, 400))
        self.assertEqual(final.mode, "RGB")
        self.assertEqual(final.getpixel((2, 2)), (237, 237, 237))
        a = np.asarray(master.getchannel("A")) > 16
        ys, xs = np.nonzero(a)
        larg, alt = (xs.max() - xs.min() + 1) / 400, (ys.max() - ys.min() + 1) / 400
        e = CFG["enquadramento"]
        self.assertTrue(abs(larg - e["ocupacao_largura"]) < 0.01 or abs(alt - e["ocupacao_altura"]) < 0.01)
        self.assertLessEqual(larg, e["ocupacao_largura"] + 0.01)
        self.assertLessEqual(alt, e["ocupacao_altura"] + 0.01)


class TestEstampar(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self.tmp.name)
        cfg = carregar_config(self.raiz / "config.json")
        cfg["enquadramento"]["lado"] = 300
        cfg["saida"]["web_lado_max"] = 300
        self.proj = Projeto(self.raiz, cfg)
        criar_mockups(self.raiz / "mockups")
        sintetico.estampa(120, 160).save(self.raiz / "arte.png")
        Image.new("RGB", (100, 60), (255, 255, 255)).save(self.raiz / "logo.jpg")  # JPG com fundo
        escrever_mapa(self.raiz / "mapa.csv", [
            LinhaMapa("prod-a", "PROD-A", "", "costas", "arte.png", origem="manual",
                      largura_rel="0.6", topo_rel="0.2", centro_x_rel="0"),
            LinhaMapa("prod-a", "PROD-A", "Preta", "frente", "arte.png"),   # sem geometria -> padrão
            LinhaMapa("prod-b", "PROD-B", "", "frente", "arte.png"),        # só frente
            LinhaMapa("prod-c", "PROD-C", "", "costas", "nao-existe.png"),
        ])
        self.mk = descobrir_mockups(self.raiz / "mockups", cfg)

    def tearDown(self):
        self.tmp.cleanup()

    def _planejar(self, **kw):
        from catalogo import Produto
        prods = [Produto("prod-a", "PROD A T-SHIRT", "PROD-A", "T-Shirt", "active", "", ["Preta", "Branca", "Azul Marinho"]),
                 Produto("prod-b", "PROD B T-SHIRT", "PROD-B", "T-Shirt", "active", "", ["Branca"]),
                 Produto("prod-c", "PROD C T-SHIRT", "PROD-C", "T-Shirt", "active", "", ["Preta", "Branca / Azul Claro"]),
                 Produto("prod-d", "PROD D T-SHIRT", "PROD-D", "T-Shirt", "active", "", ["Preta"])]
        return E.planejar(self.proj, ler_mapa(self.raiz / "mapa.csv", self.proj.cfg), self.mk, prods, **kw)

    def test_planejamento(self):
        ts = {(t.handle, t.cor): t for t in self._planejar()}
        a = ts[("prod-a", "Preta")]
        self.assertEqual([(v.vista, v.numero) for v in a.vistas], [("costas", 1), ("frente", 2), ("close-costas", 3)])
        self.assertEqual(a.vistas[0].origem_geometria, "manual")
        self.assertEqual(a.vistas[1].origem_geometria, "padrao")
        self.assertTrue(a.vistas[0].arquivo_png.endswith("saida/PROD-A/PALL-PROD-A-PT_01-costas.png"))
        self.assertTrue(a.vistas[2].arquivo_png.endswith("PALL-PROD-A-PT_03-close.png"))
        # Branca: frente sem linha -> frente lisa como 02
        b = ts[("prod-a", "Branca")]
        self.assertIsNone(b.vistas[1].estampa)
        self.assertEqual(ts[("prod-a", "Azul Marinho")].status, "sem_mockup")
        self.assertEqual([(v.vista, v.numero) for v in ts[("prod-b", "Branca")].vistas], [("frente", 1)])
        self.assertEqual(ts[("prod-c", "Branca / Azul Claro")].status, "sem_mockup")
        self.assertEqual(ts[("prod-c", "Preta")].vistas[0].status, "sem_estampa")
        self.assertEqual(ts[("prod-d", "Preta")].status, "sem_estampa")

    def test_filtros(self):
        ts = self._planejar(filtro_produtos=["prod-b"])
        self.assertEqual({t.handle for t in ts}, {"prod-b"})
        ts = self._planejar(filtro_cores=["PT"])
        self.assertEqual({t.cor for t in ts}, {"Preta"})
        ts = self._planejar(limite=1)
        self.assertEqual({t.handle for t in ts}, {"prod-a"})

    def test_gera_pula_e_forca(self):
        ts = E.executar(self._planejar(filtro_produtos=["prod-a"], filtro_cores=["Preta"]), self.proj.cfg, self.raiz, False)
        rel = E.linhas_relatorio(ts)
        self.assertEqual([r["status"] for r in rel], ["ok", "ok", "ok"], rel)
        png = self.raiz / "saida/PROD-A/PALL-PROD-A-PT_01-costas.png"
        self.assertTrue(png.exists())
        self.assertTrue((self.raiz / "saida_web/PALL-PROD-A-PT_01-costas.jpg").exists())
        self.assertTrue((self.raiz / "saida_transparente/PROD-A/PALL-PROD-A-PT_01-costas.png").exists())
        with Image.open(png) as im:
            self.assertEqual(im.size, (300, 300))
        mtime = png.stat().st_mtime_ns
        ts = self._planejar(filtro_produtos=["prod-a"], filtro_cores=["Preta"])
        self.assertTrue(all(v.status == "pulado" for t in ts for v in t.vistas))
        E.executar(ts, self.proj.cfg, self.raiz, False)
        self.assertEqual(png.stat().st_mtime_ns, mtime)
        ts = E.executar(self._planejar(filtro_produtos=["prod-a"], filtro_cores=["Preta"], forcar=True),
                        self.proj.cfg, self.raiz, False)
        self.assertTrue(all(v.status == "ok" for t in ts for v in t.vistas))

    def test_previa_e_paralelo(self):
        ts = E.executar(self._planejar(previa=True), self.proj.cfg, self.raiz, True, workers=2)
        ok = [v for t in ts for v in t.vistas if v.status in ("ok", "liso")]
        self.assertGreaterEqual(len(ok), 5)
        self.assertTrue(all("saida_previa" in v.arquivo_png for v in ok))

    def test_relatorio_csv_pela_cli(self):
        import pallacio
        rc = pallacio.main(["estampar", "--pasta", str(self.raiz), "--produto", "PROD-A", "--cor", "Preta", "--workers", "1"])
        self.assertEqual(rc, 0)
        with open(self.raiz / "relatorio.csv", encoding="utf-8") as f:
            linhas = list(csv.DictReader(f))
        self.assertTrue(any(l["status"] == "ok" for l in linhas))
        self.assertTrue((self.raiz / "folha_contato.jpg").exists())
        self.assertTrue((self.raiz / "antes_depois.html").exists())


if __name__ == "__main__":
    unittest.main()
