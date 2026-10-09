import sys
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mockups import _pistas_mockup, registrar_inclinada  # noqa: E402
import copy  # noqa: E402
from catalogo import CONFIG_PADRAO  # noqa: E402


def _camiseta(lado=600):
    im = Image.new("RGBA", (lado, int(lado * 1.3)), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.polygon([(150, 120), (450, 120), (580, 260), (500, 320), (460, 280), (460, 700),
               (140, 700), (140, 280), (100, 320), (20, 260)], fill=(20, 20, 20, 255))
    return im


class TestInclinada(unittest.TestCase):
    def test_registro_recupera_giro_e_escala(self):
        reta = _camiseta()
        incl = reta.rotate(18, resample=Image.BICUBIC, expand=True).resize((500, 560))
        reg = registrar_inclinada(reta, incl)
        self.assertGreater(reg.nota, 0.9)
        self.assertAlmostEqual(reg.angulo, -18, delta=2.5)

    def test_nome_do_mockup(self):
        cfg = copy.deepcopy(CONFIG_PADRAO)
        self.assertEqual(_pistas_mockup("preta-costas-inclinada.png", cfg), ("Preta", "costas-inclinada"))
        self.assertEqual(_pistas_mockup("preta-costas.png", cfg), ("Preta", "costas"))


if __name__ == "__main__":
    unittest.main()
