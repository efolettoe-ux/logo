"""Correções da revisão: artes para revisar não saem como 'ok', lados que faltam não travam a cor,
restos de fundo bloqueiam a imagem, tinta branca fica branca, sombra fora do tronco, legibilidade estrita,
reaproveitamento de arte (usar_tambem) e ajuste de cor da tinta."""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import casamento as C  # noqa: E402
import estampar as E  # noqa: E402
import sintetico  # noqa: E402
from catalogo import CONFIG_PADRAO, LinhaMapa, Produto, Projeto, carregar_config  # noqa: E402
from mockups import descobrir_mockups  # noqa: E402
from test_casamento import CLARA, ESCURA, arte, produto  # noqa: E402
from test_estampar import criar_mockups  # noqa: E402

CFG = CONFIG_PADRAO


class _Projeto(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self.tmp.name)
        criar_mockups(self.raiz / "mockups", close=False, chumbo=False)
        self.cfg = carregar_config(self.raiz / "config.json")
        self.cfg["enquadramento"]["lado"] = 240
        self.proj = Projeto(self.raiz, self.cfg)
        self.mk = descobrir_mockups(self.raiz / "mockups", self.cfg)
        sintetico.estampa(100, 120).save(self.raiz / "a.png")
        self.prods = [Produto("x", "X T-SHIRT", "X", "T-Shirt", "active", "", ["Preta", "Branca"])]

    def tearDown(self):
        self.tmp.cleanup()


class TestRevisarEFalta(_Projeto):
    def test_revisar_nao_gera_e_manual_gera(self):
        mapa = [LinhaMapa("x", "X", "Preta", "costas", "a.png", revisar="sim", observacao="arte com problema: fundo_sujo"),
                LinhaMapa("x", "X", "Preta", "frente", "LISO"),
                LinhaMapa("x", "X", "Branca", "costas", "a.png", revisar="sim", origem="manual"),
                LinhaMapa("x", "X", "Branca", "frente", "LISO")]
        ts = {t.cor: t for t in E.planejar(self.proj, mapa, self.mk, self.prods)}
        pt = {v.vista: v for v in ts["Preta"].vistas}
        self.assertEqual(pt["costas"].status, "revisar")
        self.assertIn("fundo_sujo", pt["costas"].observacao)
        self.assertEqual(pt["frente"].status, "")          # a frente lisa continua sendo gerada
        self.assertEqual({v.vista: v.status for v in ts["Branca"].vistas}["costas"], "")  # manual: gera
        ts2 = {t.cor: t for t in E.planejar(self.proj, mapa, self.mk, self.prods, incluir_revisar=True)}
        self.assertEqual({v.vista: v.status for v in ts2["Preta"].vistas}["costas"], "")

    def test_frente_sem_arte_sai_lisa(self):
        mapa = [LinhaMapa("x", "X", "Preta", "costas", "a.png"), LinhaMapa("x", "X", "Preta", "frente", "")]
        t = E.planejar(self.proj, mapa, self.mk, self.prods[:1], filtro_cores=["Preta"])[0]
        st = {(v.vista, v.numero): (v.status, v.estampa) for v in t.vistas}
        self.assertEqual(st[("frente", 2)], ("", None))  # padrão: frente lisa, só na cor

    def test_falta_so_a_frente_gera_as_costas(self):
        self.cfg["estampar"]["frente_sem_arte"] = "faltando"
        mapa = [LinhaMapa("x", "X", "Preta", "costas", "a.png"), LinhaMapa("x", "X", "Preta", "frente", "")]
        t = E.planejar(self.proj, mapa, self.mk, self.prods[:1], filtro_cores=["Preta"])[0]
        self.assertFalse(t.status)
        st = {(v.vista, v.numero): v.status for v in t.vistas}
        self.assertEqual(st[("costas", 1)], "")
        self.assertEqual(st[("frente", 2)], "sem_estampa")
        rel = E.linhas_relatorio(E.executar([t], self.cfg, self.raiz, False))
        self.assertEqual(sorted(r["status"] for r in rel), ["ok", "sem_estampa"])
        self.assertTrue((self.raiz / "saida/X/PALL-X-PT_01-costas.png").exists())
        self.assertFalse((self.raiz / "saida/X/PALL-X-PT_02-frente.png").exists())

    def test_so_cores_completas(self):
        self.cfg["estampar"]["so_cores_completas"] = True
        self.cfg["estampar"]["frente_sem_arte"] = "faltando"
        mapa = [LinhaMapa("x", "X", "Preta", "costas", "a.png"), LinhaMapa("x", "X", "Preta", "frente", "")]
        t = E.planejar(self.proj, mapa, self.mk, self.prods[:1], filtro_cores=["Preta"])[0]
        self.assertEqual(t.status, "sem_estampa")

    def test_residuo_de_fundo_bloqueia(self):
        # arte com "nuvem" cinza em degradê embaixo (resto de fundo que não saiu)
        im = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.ellipse([90, 40, 210, 160], fill=(220, 90, 30, 255))
        faixa = np.zeros((300, 300, 4), np.uint8)
        for y in range(200, 300):
            v = int(200 - (y - 200) * 1.8)
            faixa[y, :, :3] = v
            faixa[y, :, 3] = 255
        im = Image.alpha_composite(im, Image.fromarray(faixa, "RGBA"))
        im.save(self.raiz / "suja.png")
        from imagem import residuo_de_fundo
        self.assertIsNotNone(residuo_de_fundo(im))
        self.assertIsNone(residuo_de_fundo(sintetico.estampa()))
        # texto branco chapado (sem cor, liso) não é resto de fundo
        txt = Image.new("RGBA", (300, 120), (0, 0, 0, 0))
        ImageDraw.Draw(txt).rectangle([10, 10, 290, 110], fill=(255, 255, 255, 255))
        self.assertIsNone(residuo_de_fundo(txt))
        mapa = [LinhaMapa("x", "X", "Preta", "costas", "suja.png"), LinhaMapa("x", "X", "Preta", "frente", "LISO")]
        ts = E.executar(E.planejar(self.proj, mapa, self.mk, self.prods[:1], filtro_cores=["Preta"]),
                        self.cfg, self.raiz, False)
        st = {v.vista: v.status for v in ts[0].vistas}
        self.assertEqual(st["costas"], "revisar")
        self.assertFalse((self.raiz / "saida/X/PALL-X-PT_01-costas.png").exists())


class TestTintaECompositor(unittest.TestCase):
    def test_tinta_branca_fica_branca_na_preta(self):
        from compositor import aplicar_estampa, preparar_mockup
        mk = preparar_mockup(sintetico.mockup_liso(300, 400, (16, 16, 16)), CFG)
        branca = Image.new("RGBA", (80, 80), (255, 255, 255, 255))
        t = mk.torso
        caixa = (t.cx - 40, t.topo + 0.3 * t.altura, 80, 80)
        out = np.asarray(aplicar_estampa(mk, branca, caixa, CFG).convert("RGB")).astype(int)
        x, y = int(t.cx), int(t.topo + 0.3 * t.altura + 40)
        miolo = out[y - 15:y + 15, x - 15:x + 15]
        self.assertGreaterEqual(np.percentile(miolo, 95), 248)

    def test_ajuste_de_tinta(self):
        from imagem import ajustar_tinta, ler_ajuste_tinta, rgb_para_lab
        self.assertEqual(ler_ajuste_tinta("L=+10;a=-2;b=+3.5"), (10.0, -2.0, 3.5))
        self.assertIsNone(ler_ajuste_tinta(""))
        im = Image.new("RGBA", (40, 40), (40, 60, 200, 255))
        ImageDraw.Draw(im).rectangle([0, 0, 5, 5], fill=(0, 0, 0, 255))  # detalhe preto pequeno
        out = np.asarray(ajustar_tinta(im, (20.0, 0.0, 0.0)))
        L0 = rgb_para_lab(np.asarray(im)[20, 20, :3][None, None])[0, 0, 0]
        L1 = rgb_para_lab(out[20, 20, :3][None, None])[0, 0, 0]
        self.assertAlmostEqual(L1 - L0, 20, delta=2)
        self.assertLess(out[2, 2, :3].max(), 30)  # o preto quase não muda
        self.assertTrue((out[..., 3] == 255).all())


class TestTroncoSemSombra(unittest.TestCase):
    def test_sombra_suave_fora_do_tronco(self):
        from imagem import Torso, refinar_largura_torso
        W, H = 600, 600
        fundo = np.full((H, W), 232.0)
        # sombra: rampa que escurece até a borda do tecido (x 150..450), tecido preto
        for x in range(130, 150):
            fundo[:, x] = 232 - (x - 130) * 1.6
            fundo[:, W - 1 - x] = 232 - (x - 130) * 1.6
        fundo[:, 150:450] = 22
        im = Image.fromarray(fundo.astype(np.uint8), "L").convert("RGB")
        t = Torso(135, 465, 100, 560, 200, W, H)   # largura medida com a sombra
        r = refinar_largura_torso(im, t)
        self.assertAlmostEqual(r.x0, 150, delta=1.5)
        self.assertAlmostEqual(r.x1, 450, delta=1.5)

    def test_fator_de_tamanho(self):
        from imagem import Torso
        t = Torso(0, 513, 0, 1000, 500, 600, 1100)
        f = E.fator_tamanho(0.562, t, CFG)
        self.assertAlmostEqual(f, (0.562 / 0.513) ** 0.5, places=3)
        self.assertEqual(E.fator_tamanho(None, t, CFG), 1.0)


class TestCasarRevisao(unittest.TestCase):
    def test_legibilidade_usa_a_parte_menos_contrastante(self):
        # arte para camisa clara: quase toda clara, mas com 10% de texto preto -> some na Preta
        a = arte("a/clara.png", para="clara", l=(40, 70, 90), tinta_l10="5", tinta_l90="95")
        self.assertFalse(C.legivel(a, "Preta", CFG, estrito=True))
        b = arte("a/b.png", para="clara", l=(60, 70, 90), tinta_l10="55", tinta_l90="95")
        self.assertTrue(C.legivel(b, "Preta", CFG, estrito=True))
        cands = [a]
        self.assertIsNone(C.escolher_arte(cands, "Preta", CFG)[0])

    def test_usar_tambem(self):
        a = arte("FOI/logo.png", produto="CAPRESE T-SHIRT", lado="frente", para="escura", l=ESCURA,
                 usar_tambem="VESPA T-SHIRT:frente:escura")
        m = C.montar_mapa([produto("VESPA T-SHIRT", cores=["Preta"], lados=("frente",))], [a], [], CFG)
        r = [x for x in m if x["lado"] == "frente"][0]
        self.assertEqual(r["arquivo_estampa"], "FOI/logo.png")
        self.assertIn("reaproveitada", r["observacao"])

    def test_tinta_diferente_da_loja(self):
        p = produto("DOLCE T-SHIRT", cores=["Preta"])
        a = arte("FOI/d.png", produto="DOLCE T-SHIRT", para="escura", l=ESCURA)
        dif_mono = {"dL": -20.0, "da": 0.0, "db": 2.0, "dE": 20.1, "dC": 1.0, "mono": 0.9, "nota": 0.8}
        m = C.montar_mapa([p], [a], [], CFG, tintas={("dolce", "Preta", "costas"): {"FOI/d.png": dif_mono}})
        r = [x for x in m if x["lado"] == "costas"][0]
        self.assertTrue(r["ajuste_tinta"].startswith("L=+20.0"))
        self.assertEqual(r["revisar"], "nao")
        dif_multi = dict(dif_mono, mono=0.3, dC=30.0)
        m = C.montar_mapa([p], [a], [], CFG, tintas={("dolce", "Preta", "costas"): {"FOI/d.png": dif_multi}})
        r = [x for x in m if x["lado"] == "costas"][0]
        self.assertEqual(r["revisar"], "sim")
        self.assertIn("outra versão", r["observacao"])


if __name__ == "__main__":
    unittest.main()
