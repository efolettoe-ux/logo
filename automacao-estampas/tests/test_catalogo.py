import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from catalogo import (CONFIG_PADRAO, LinhaMapa, carregar_config, escrever_mapa, ler_mapa, nome_arquivo_saida,  # noqa: E402
                      nome_produto, normalizar_cor, numeracao_lados, tabela_cores)

CFG = CONFIG_PADRAO
SUF = CFG["tipos"]["camiseta"]["sufixos_titulo"]


class TestNomes(unittest.TestCase):
    def test_nome_produto(self):
        self.assertEqual(nome_produto("CAPRESE T-SHIRT", SUF), "CAPRESE")
        self.assertEqual(nome_produto("COTE D' AZUR T-SHIRT", SUF), "COTE-D-AZUR")
        self.assertEqual(nome_produto("ÁLCOOL T-SHIRT", SUF), "ALCOOL")
        self.assertEqual(nome_produto("MONEY TALKS T-SHIRT", SUF), "MONEY-TALKS")

    def test_arquivo_saida(self):
        self.assertEqual(nome_arquivo_saida("CAPRESE", "PT", 1, "costas", "png", CFG), "PALL-CAPRESE-PT_01-costas.png")
        self.assertEqual(nome_arquivo_saida("CAPRESE", "OW", 3, "close", "png", CFG), "PALL-CAPRESE-OW_03-close.png")

    def test_numeracao_regra_da_marca(self):
        self.assertEqual(numeracao_lados(True, False, CFG), {"costas": 1, "frente": 2})
        self.assertEqual(numeracao_lados(True, True, CFG), {"costas": 1, "frente": 2})
        self.assertEqual(numeracao_lados(False, True, CFG), {"frente": 1})


class TestCores(unittest.TestCase):
    def test_azul_marinho_minusculo(self):
        self.assertEqual(normalizar_cor("Azul marinho", CFG), ("Azul Marinho", True))
        self.assertEqual(normalizar_cor("off white", CFG), ("Off White", True))
        self.assertEqual(normalizar_cor("PRETA", CFG), ("Preta", True))

    def test_bicolor_e_especial(self):
        nome, ok = normalizar_cor("Branca / Azul Claro", CFG)
        self.assertEqual(nome, "Branca / Azul Claro")
        self.assertTrue(ok)
        self.assertTrue(next(c for c in tabela_cores(CFG) if c.nome == nome).especial)

    def test_chumbo_desativado(self):
        ch = next(c for c in tabela_cores(CFG) if c.nome == "Chumbo")
        self.assertFalse(ch.ativa)
        self.assertEqual(ch.codigo, "CH")


class TestConfigEMapa(unittest.TestCase):
    def test_config_criada_e_mesclada(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.json"
            cfg = carregar_config(p)
            self.assertTrue(p.exists())
            self.assertEqual(cfg["enquadramento"]["cor_fundo"], [237, 237, 237])
            p.write_text('{"enquadramento": {"lado": 1000}}', encoding="utf-8")
            cfg = carregar_config(p)
            self.assertEqual(cfg["enquadramento"]["lado"], 1000)
            self.assertIn("ocupacao_largura", cfg["enquadramento"])  # chave nova do padrão continua

    def test_mapa_ponto_e_virgula_e_virgula_decimal(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "mapa.csv"
            p.write_text("handle;NOME;cor;lado;arquivo_estampa;largura_rel;topo_rel;centro_x_rel;origem\n"
                         "caprese;CAPRESE;Azul marinho;Costas;a.png;0,62;0,19;0;manual\n", encoding="utf-8")
            ls = ler_mapa(p, CFG)
            self.assertEqual(len(ls), 1)
            self.assertEqual(ls[0].cor, "Azul Marinho")
            self.assertEqual(ls[0].lado, "costas")
            self.assertEqual(ls[0].geometria(), (0.62, 0.19, 0.0))

    def test_mapa_ida_e_volta_preserva_manual(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "mapa.csv"
            escrever_mapa(p, [LinhaMapa("x", "X", "Preta", "costas", "a.png", origem="manual", largura_rel="0.5",
                                        topo_rel="0.2", centro_x_rel="0")])
            l = ler_mapa(p, CFG)[0]
            self.assertEqual(l.origem, "manual")
            self.assertTrue(l.tem_estampa)

    def test_liso(self):
        self.assertTrue(LinhaMapa("x", lado="frente", id_normalizado="liso").eh_liso)
        self.assertFalse(LinhaMapa("x", lado="frente", id_normalizado="liso").tem_estampa)


if __name__ == "__main__":
    unittest.main()
