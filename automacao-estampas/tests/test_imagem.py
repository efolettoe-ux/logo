import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from catalogo import CONFIG_PADRAO as CFG  # noqa: E402
from imagem import (analisar_imagem, classificar_cor, desfocar, preparar_peca, remover_fundo,  # noqa: E402
                    caixa_da_geometria, geometria_relativa)
import sintetico  # noqa: E402


class TestSegmentacaoETronco(unittest.TestCase):
    def test_tronco_mockup_transparente(self):
        im = sintetico.mockup_liso(600, 800)
        _, t = preparar_peca(im, CFG)
        self.assertAlmostEqual(t.x0, 0.28 * 600, delta=6)
        self.assertAlmostEqual(t.x1, 0.72 * 600, delta=6)
        self.assertAlmostEqual(t.base, 0.80 * 800, delta=6)
        self.assertAlmostEqual(t.topo, 0.20 * 800, delta=8)

    def test_camiseta_branca_em_fundo_cinza_claro(self):
        foto = sintetico.foto_loja(cor=(242, 242, 244))
        _, t = preparar_peca(foto, CFG)
        self.assertAlmostEqual(t.largura, 0.44 * 800, delta=10)

    def test_estampa_medida_relativa_ao_tronco(self):
        # tronco: x 224..576 (352 px), topo 160, base 640 (480 px)
        caixa = (300, 260, 500, 520)
        for cor in [(23, 23, 22), (241, 241, 243), (40, 47, 67)]:
            a = analisar_imagem(sintetico.foto_loja(cor=cor, estampa_caixa=caixa), CFG)
            g = a.geometria
            self.assertIsNotNone(g, cor)
            self.assertAlmostEqual(g["largura_rel"], 200 / 352, delta=0.03)
            self.assertAlmostEqual(g["topo_rel"], (260 - 160) / 480, delta=0.03)
            self.assertAlmostEqual(g["centro_x_rel"], 0.0, delta=0.02)

    def test_geometria_ida_e_volta(self):
        _, t = preparar_peca(sintetico.mockup_liso(), CFG)
        g = geometria_relativa((250, 300, 350, 420), t)
        x, y, w, h = caixa_da_geometria(t, g["largura_rel"], g["topo_rel"], g["centro_x_rel"], g["aspecto"])
        self.assertAlmostEqual(x, 250, delta=0.5)
        self.assertAlmostEqual(y, 300, delta=0.5)
        self.assertAlmostEqual(w, 100, delta=0.5)
        self.assertAlmostEqual(h, 120, delta=0.5)


class TestCores(unittest.TestCase):
    def test_classifica_cores_da_loja(self):
        self.assertEqual(classificar_cor((241, 241, 243), CFG).nome, "Branca")
        self.assertEqual(classificar_cor((240, 234, 221), CFG).nome, "Off White")
        self.assertEqual(classificar_cor((23, 23, 22), CFG).nome, "Preta")
        self.assertEqual(classificar_cor((40, 47, 67), CFG).nome, "Azul Marinho")


class TestRemoverFundo(unittest.TestCase):
    def _arte(self, fundo, tinta):
        im = Image.new("RGB", (300, 300), fundo)
        d = ImageDraw.Draw(im)
        d.ellipse([40, 40, 260, 260], fill=tinta)
        d.ellipse([100, 100, 200, 200], fill=fundo)      # miolo grande da cor do fundo: fica
        d.ellipse([60, 140, 75, 155], fill=fundo)        # buraco pequeno (miolo de letra): sai
        return im.resize((600, 600), Image.LANCZOS).resize((300, 300), Image.LANCZOS)  # bordas suaves

    def test_fundo_branco_sem_halo(self):
        rgba, ok = remover_fundo(self._arte((255, 255, 255), (20, 40, 160)))
        self.assertTrue(ok)
        a = np.asarray(rgba)
        self.assertEqual(a[5, 5, 3], 0)                  # canto: fundo removido
        self.assertEqual(a[150, 150, 3], 255)            # miolo grande preservado
        self.assertEqual(a[147, 67, 3], 0)               # buraco pequeno removido
        borda = (a[..., 3] > 20) & (a[..., 3] < 235)
        self.assertTrue(borda.any())
        # descontaminado: pixels da transição têm a cor da tinta, não um azul esbranquiçado
        self.assertLess(np.median(a[borda][:, :3].astype(int).sum(axis=1)), 300)

    def test_fundo_preto(self):
        rgba, ok = remover_fundo(self._arte((0, 0, 0), (240, 220, 30)))
        self.assertTrue(ok)
        a = np.asarray(rgba)
        self.assertEqual(a[5, 5, 3], 0)
        borda = (a[..., 3] > 20) & (a[..., 3] < 235)
        self.assertGreater(np.median(a[borda][:, 0].astype(int)), 180)  # sem halo escuro

    def test_borda_nao_lisa_nao_mexe(self):
        rng = np.random.default_rng(0)
        im = Image.fromarray(rng.integers(0, 255, (100, 100, 3), dtype=np.uint8))
        _, ok = remover_fundo(im)
        self.assertFalse(ok)


class TestDesfoque(unittest.TestCase):
    def test_conserva_media(self):
        a = np.random.default_rng(1).random((50, 60)).astype(np.float32)
        for s in (0.5, 1.0, 3.0):
            self.assertAlmostEqual(float(desfocar(a, s).mean()), float(a.mean()), places=2)


if __name__ == "__main__":
    unittest.main()
