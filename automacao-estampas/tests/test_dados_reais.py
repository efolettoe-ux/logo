"""Testes com os arquivos reais do usuário (pulados se a pasta não existir nesta máquina).

Defina PALLACIO_UPLOAD para apontar para a pasta com 'CAMISETAS 100%' e 'CAMISETAS 5 CORES - cópia'.
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from catalogo import CONFIG_PADRAO as CFG  # noqa: E402

UPLOAD = Path(os.environ.get("PALLACIO_UPLOAD",
                             "/tmp/claude-0/-home-user-logo/2cf89407-8e22-55ba-910c-d0e8feb0d3ba/scratchpad/upload"))
JA_FOI = UPLOAD / "CAMISETAS 100%" / "JA FOI"
MOCKUPS = UPLOAD / "CAMISETAS 5 CORES - cópia"


@unittest.skipUnless(JA_FOI.is_dir(), "fotos reais (JA FOI) não estão nesta máquina")
class TestFotosDaLoja(unittest.TestCase):
    def test_caprese_costas_preta(self):
        from imagem import analisar_imagem
        a = analisar_imagem(JA_FOI / "CAPRESE T-SHIRT" / "2.png", CFG)
        self.assertEqual(a.cor.nome, "Preta")
        g = a.geometria
        # tronco medido na borda nítida do tecido (sem a sombra): ~420 px nesta foto 1254x1254
        self.assertAlmostEqual(a.torso.largura, 420, delta=6)
        self.assertAlmostEqual(g["largura_rel"], 0.635, delta=0.02)
        self.assertAlmostEqual(g["topo_rel"], 0.194, delta=0.02)
        self.assertAlmostEqual(g["centro_x_rel"], 0.0, delta=0.02)

    def test_mesma_medida_em_todas_as_cores(self):
        from imagem import analisar_imagem
        larg = {}
        for n in (2, 4, 6, 8):  # costas da CAPRESE nas 4 cores
            a = analisar_imagem(JA_FOI / "CAPRESE T-SHIRT" / f"{n}.png", CFG)
            larg[a.cor.nome] = a.geometria["largura_rel"]
        self.assertEqual(set(larg), {"Preta", "Azul Marinho", "Branca", "Off White"})
        self.assertLess(max(larg.values()) - min(larg.values()), 0.03)

    def test_tronco_sem_sombra_em_todas_as_cores(self):
        from imagem import analisar_imagem
        for n in range(1, 9):
            a = analisar_imagem(JA_FOI / "DOLCE T-SHIRT" / f"{n}.png", CFG)
            self.assertTrue(408 <= a.torso.largura <= 426, f"{n}.png: {a.torso.largura:.1f}")

    def test_frente_lisa_sem_estampa(self):
        from imagem import analisar_imagem
        a = analisar_imagem(JA_FOI / "RIVIERA T-SHIRT" / "7.png", CFG)  # frente preta lisa (só etiqueta)
        self.assertIsNone(a.estampa)

    def test_logo_de_peito(self):
        from imagem import analisar_imagem
        a = analisar_imagem(JA_FOI / "COTE D' AZUR T-SHIRT" / "5.png", CFG)  # frente branca, logo dourado
        self.assertEqual(a.cor.nome, "Branca")
        self.assertAlmostEqual(a.geometria["largura_rel"], 0.23, delta=0.03)
        self.assertGreater(a.geometria["centro_x_rel"], 0.2)


@unittest.skipUnless(MOCKUPS.is_dir(), "mockups reais não estão nesta máquina")
class TestMockupsReais(unittest.TestCase):
    def test_descoberta(self):
        from mockups import descobrir_mockups
        r = descobrir_mockups(MOCKUPS, CFG)
        self.assertEqual(len(r.mockups), 12)  # 4 cores x 3 vistas (chumbo desativado)
        self.assertEqual(r.cores_completas(), {"Preta", "Branca", "Off White", "Azul Marinho"})

    def test_tronco_igual_em_todas_as_cores(self):
        from compositor import preparar_mockup
        larguras = [preparar_mockup(MOCKUPS / f"{c}-costas.png", CFG).torso.largura
                    for c in ("preta", "branca", "off-white", "azul-marinho")]
        self.assertLess(max(larguras) - min(larguras), 5)
        self.assertAlmostEqual(larguras[0], 928, delta=15)

    def test_registro_close(self):
        from imagem import carregar_imagem
        from mockups import registrar_close
        reg = registrar_close(carregar_imagem(MOCKUPS / "preta-costas.png"), carregar_imagem(MOCKUPS / "preta-close-costas.png"))
        self.assertAlmostEqual(reg.escala, 1.866, delta=0.02)
        self.assertAlmostEqual(reg.tx, 415, delta=4)
        self.assertAlmostEqual(reg.ty, 224, delta=4)
        self.assertGreater(reg.nota, 0.6)


if __name__ == "__main__":
    unittest.main()


DADOS = Path(__file__).resolve().parents[1] / "dados"


@unittest.skipUnless((UPLOAD / "NOVAS").is_dir(), "pastas reais de artes não estão nesta máquina")
class TestInventarioReal(unittest.TestCase):
    def test_todos_os_arquivos_existem(self):
        import casamento as C
        inv = C.ler_inventario(DADOS / "inventario.csv")
        self.assertEqual(len(inv), 659)
        faltando = [l["caminho"] for l in inv if not (UPLOAD / l["caminho"]).exists()]
        self.assertEqual(faltando, [])

    def test_uma_escolhida_por_produto_lado_tinta(self):
        import casamento as C
        from collections import Counter
        inv = C.ler_inventario(DADOS / "inventario.csv")
        c = Counter((l["produto"], l["lado"], l["para_camisa"], l["cor_especifica"]) for l in inv if l["escolhida"] == "sim")
        self.assertEqual(max(c.values()), 1)
        # cópias idênticas nunca são escolhidas
        self.assertFalse([l for l in inv if l["escolhida"] == "sim" and l["duplicata_de"]])


@unittest.skipUnless((DADOS / "mapa.csv").exists(), "dados/mapa.csv não existe")
class TestMapaReal(unittest.TestCase):
    def test_estrutura(self):
        from catalogo import ler_csv_dicts, ler_mapa
        import casamento as C
        linhas = ler_csv_dicts(DADOS / "mapa.csv")
        self.assertEqual(list(linhas[0].keys()), C.COLUNAS_MAPA_CASAR)
        self.assertEqual(len({l["handle"] for l in linhas}), 169)
        self.assertEqual({l["lado"] for l in linhas}, {"costas", "frente"})
        self.assertTrue(all(l["origem"] in ("medido", "padrao", "manual", "") for l in linhas))
        # o estampar lê o mesmo arquivo
        self.assertEqual(len(ler_mapa(DADOS / "mapa.csv", CFG)), len(linhas))
        if (UPLOAD / "NOVAS").is_dir():
            sem = [l["arquivo_estampa"] for l in linhas if l["arquivo_estampa"] not in ("", "LISO")
                   and not (UPLOAD / l["arquivo_estampa"]).exists()]
            self.assertEqual(sem, [])
        # as 12 camisetas JA FOI usam a medida da foto atual
        caprese = [l for l in linhas if l["handle"] == "caprese" and l["lado"] == "costas"]
        self.assertTrue(all(l["origem"] == "medido" for l in caprese))
