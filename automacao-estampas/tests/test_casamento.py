"""casar: escolha da arte por cor (tinta clara/escura), duplicatas, mapa.csv, linhas manuais, arquivos novos."""
import copy
import csv
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import casamento as C  # noqa: E402
import sintetico  # noqa: E402
from catalogo import CONFIG_PADRAO, Produto, Projeto, carregar_config, ler_csv_dicts  # noqa: E402

CFG = CONFIG_PADRAO
CORES4 = ["Branca", "Off White", "Preta", "Azul Marinho"]


def arte(caminho, produto="CAPRESE T-SHIRT", lado="costas", para="clara", l=(10, 20, 30), **kw):
    d = {k: "" for k in C.COLUNAS_INVENTARIO}
    d.update({"caminho": caminho, "tipo": "estampa", "produto": produto, "lado": lado, "para_camisa": para,
              "qualidade": "ok", "tem_alpha": "sim", "largura": "2000", "altura": "2000", "aspecto_arte": "1.2",
              "tinta_l25": str(l[0]), "tinta_l50": str(l[1]), "tinta_l75": str(l[2]), "versao_preferida": "sim",
              "origem": "inventario"})
    d.update(kw)
    return d


def produto(titulo="CAPRESE T-SHIRT", cores=None, lados=("costas",), handle=None):
    nome = titulo.replace(" T-SHIRT", "").replace(" ", "-")
    p = Produto(handle or nome.lower(), titulo, nome, "T-Shirt", "active", "", list(cores or CORES4))
    p.lados_descricao = list(lados)
    return p


ESCURA = (85, 92, 97)    # tinta clara (para camisa escura)
CLARA = (8, 15, 25)      # tinta escura (para camisa clara)
VERMELHA = (45, 50, 55)  # tinta colorida de luminosidade média


class TestEscolha(unittest.TestCase):
    def test_versao_certa_por_cor(self):
        cands = [arte("a/clara.png", para="clara", l=CLARA), arte("a/escura.png", para="escura", l=ESCURA)]
        self.assertEqual(C.escolher_arte(cands, "Off White", CFG)[0]["caminho"], "a/clara.png")
        self.assertEqual(C.escolher_arte(cands, "Azul Marinho", CFG)[0]["caminho"], "a/escura.png")

    def test_cor_especifica_vence(self):
        cands = [arte("a/clara.png", para="clara", l=CLARA),
                 arte("a/ow.png", para="clara", cor_especifica="Off White", l=CLARA)]
        self.assertEqual(C.escolher_arte(cands, "Off White", CFG)[0]["caminho"], "a/ow.png")
        self.assertEqual(C.escolher_arte(cands, "Branca", CFG)[0]["caminho"], "a/clara.png")

    def test_so_tinta_escura_nao_vai_na_preta(self):
        cands = [arte("a/clara.png", para="clara", l=CLARA)]
        a, nivel, obs = C.escolher_arte(cands, "Preta", CFG)
        self.assertIsNone(a)
        self.assertIn("falta a versão para camisa escura", obs)

    def test_tinta_colorida_serve_com_revisao(self):
        cands = [arte("a/vermelha.png", para="clara", l=VERMELHA)]
        a, nivel, obs = C.escolher_arte(cands, "Preta", CFG)
        self.assertEqual(a["caminho"], "a/vermelha.png")
        self.assertEqual(nivel, 5)

    def test_todas_e_indefinida(self):
        self.assertEqual(C.escolher_arte([arte("t.png", para="todas", l=VERMELHA)], "Preta", CFG)[1], 3)
        a, nivel, _ = C.escolher_arte([arte("q.png", para="?", l=VERMELHA)], "Branca", CFG)
        self.assertEqual((a["caminho"], nivel), ("q.png", 4))

    def test_prioridade_png_transparente_e_fonte(self):
        cands = [arte("NOVAS/x.jpeg", tem_alpha="nao", largura="4000", altura="4000", l=CLARA),
                 arte("ESTAMPAS PRONTAS P: IZZY/x.png", l=CLARA),
                 arte("MATERIAL QUALITY 100%/x.png", l=CLARA, qualidade="texto_errado")]
        self.assertEqual(C.escolher_arte(cands, "Branca", CFG)[0]["caminho"], "ESTAMPAS PRONTAS P: IZZY/x.png")

    def test_visual_vence_com_margem(self):
        cands = [arte("ESTAMPAS PRONTAS P: IZZY/a.png", l=CLARA), arte("NOVAS/b.jpeg", tem_alpha="nao", l=CLARA)]
        a = C.escolher_arte(cands, "Branca", CFG, {"ESTAMPAS PRONTAS P: IZZY/a.png": 0.5, "NOVAS/b.jpeg": 0.8})[0]
        self.assertEqual(a["caminho"], "NOVAS/b.jpeg")
        a = C.escolher_arte(cands, "Branca", CFG, {"ESTAMPAS PRONTAS P: IZZY/a.png": 0.75, "NOVAS/b.jpeg": 0.8})[0]
        self.assertEqual(a["caminho"], "ESTAMPAS PRONTAS P: IZZY/a.png")

    def test_geometria_padrao_pela_proporcao(self):
        larga = C.geometria_padrao_arte("costas", 0.6, CFG)[0]
        normal = C.geometria_padrao_arte("costas", 1.3, CFG)[0]
        alta = C.geometria_padrao_arte("costas", 1.9, CFG)[0]
        self.assertAlmostEqual(larga, 0.72, places=3)
        self.assertLess(alta, normal)
        self.assertLessEqual(alta * 1.9 * 0.59, 0.546)
        self.assertAlmostEqual(C.geometria_padrao_arte("frente", 0.3, CFG)[0], 0.226, places=3)


class TestMapa(unittest.TestCase):
    def setUp(self):
        self.inv = [arte("A/clara.png", l=CLARA), arte("A/escura.png", para="escura", l=ESCURA),
                    arte("A/frente.png", lado="frente", para="todas", l=VERMELHA, aspecto_arte="0.3")]

    def _linhas(self, mapa, **f):
        return [r for r in mapa if all(r[k] == v for k, v in f.items())]

    def test_uma_linha_por_cor_e_lado(self):
        p = produto(lados=("costas",))
        m = C.montar_mapa([p], self.inv, [], CFG)
        self.assertEqual(len(m), 8)
        r = self._linhas(m, cor="Preta", lado="costas")[0]
        self.assertEqual((r["arquivo_estampa"], r["origem"], r["revisar"]), ("A/escura.png", "padrao", "nao"))
        self.assertEqual(r["largura_rel"], "%.4f" % C.geometria_padrao_arte("costas", 1.2, CFG)[0])
        # frente: arquivo existe mas a descrição não cita frente -> usa e manda revisar
        r = self._linhas(m, cor="Branca", lado="frente")[0]
        self.assertEqual((r["arquivo_estampa"], r["revisar"]), ("A/frente.png", "sim"))

    def test_frente_lisa_e_falta(self):
        inv = self.inv[:2]
        m = C.montar_mapa([produto(lados=("costas",))], inv, [], CFG)
        self.assertEqual(self._linhas(m, cor="Branca", lado="frente")[0]["arquivo_estampa"], C.LISO)
        m = C.montar_mapa([produto(lados=("frente", "costas"))], inv, [], CFG)
        r = self._linhas(m, cor="Branca", lado="frente")[0]
        self.assertEqual((r["arquivo_estampa"], r["revisar"]), ("", "sim"))
        self.assertIn("falta", r["observacao"])

    def test_medida_da_foto_atual(self):
        analise = [{"handle": "caprese", "lado": "costas", "tem_estampa": "sim", "largura_rel": "0.61",
                    "topo_rel": "0.19", "centro_x_rel": "0.0", "cor": "Preta"},
                   {"handle": "caprese", "lado": "costas", "tem_estampa": "sim", "largura_rel": "0.63",
                    "topo_rel": "0.21", "centro_x_rel": "0.01", "cor": "Branca"},
                   {"handle": "caprese", "lado": "frente", "tem_estampa": "nao", "cor": "Preta"}]
        m = C.montar_mapa([produto(lados=("frente", "costas"))], self.inv, analise, CFG)
        r = self._linhas(m, cor="Off White", lado="costas")[0]
        self.assertEqual((r["origem"], r["largura_rel"], r["topo_rel"]), ("medido", "0.6200", "0.2000"))
        # a foto mostra a frente lisa: segue a loja, mesmo com descrição e arquivo de frente
        r = self._linhas(m, cor="Off White", lado="frente")[0]
        self.assertEqual(r["arquivo_estampa"], C.LISO)

    def test_linhas_manuais_ficam(self):
        manual = {k: "" for k in C.COLUNAS_MAPA_CASAR}
        manual.update({"handle": "caprese", "cor": "Preta", "lado": "costas", "arquivo_estampa": "minha.png",
                       "origem": "manual", "largura_rel": "0.5"})
        m = C.montar_mapa([produto()], self.inv, [], CFG, manuais=[manual])
        r = self._linhas(m, cor="Preta", lado="costas")[0]
        self.assertEqual((r["arquivo_estampa"], r["largura_rel"], r["origem"]), ("minha.png", "0.5", "manual"))
        self.assertEqual(len(m), 8)

    def test_ler_manuais_do_csv(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "mapa.csv"
            p.write_text("handle;cor;lado;arquivo_estampa;origem\ncaprese;azul marinho;costas;x.png;manual\n"
                         "caprese;Preta;costas;y.png;padrao\n", encoding="utf-8")
            ms = C.ler_manuais(p)
            self.assertEqual(len(ms), 1)
            self.assertEqual(ms[0]["cor"], "Azul Marinho")

    def test_arquivo_sumido_nao_entra(self):
        m = C.montar_mapa([produto()], self.inv, [], CFG, existe=lambda c: c != "A/escura.png")
        r = self._linhas(m, cor="Preta", lado="costas")[0]
        self.assertEqual(r["arquivo_estampa"], "")
        self.assertEqual(r["revisar"], "sim")

    def test_cor_especial(self):
        m = C.montar_mapa([produto(cores=["Branca / Azul Claro"])], self.inv, [], CFG)
        self.assertIn("bicolor", m[0]["observacao"])


class TestDuplicatas(unittest.TestCase):
    def test_exata_mantem_original(self):
        ls = [arte("M/x - cópia.png", sha1="abc"), arte("M/x.png", sha1="abc")]
        rem = C.marcar_duplicatas(ls, CFG)
        self.assertEqual(rem, [("M/x - cópia.png", "M/x.png", "exata")])
        self.assertEqual(ls[0]["versao_preferida"], "nao")

    def test_visual_nao_mistura_tinta_clara_e_escura(self):
        ls = [arte("I/a.png", para="clara", hash_visual="ffff0000ffff0000", l=CLARA),
              arte("I/b.png", para="escura", hash_visual="ffff0000ffff0000", l=CLARA),
              arte("N/c.jpeg", para="clara", hash_visual="ffff0000ffff0001", tem_alpha="nao", l=CLARA)]
        rem = C.marcar_duplicatas(ls, CFG)
        self.assertEqual(rem, [("N/c.jpeg", "I/a.png", "visual")])

    def test_escolhidas(self):
        ls = [arte("NOVAS/a.jpeg", tem_alpha="nao"), arte("ESTAMPAS PRONTAS P: IZZY/a.png")]
        C.marcar_escolhidas(ls, CFG)
        self.assertEqual([l["escolhida"] for l in ls], ["alternativa", "sim"])


class TestFichaEVisual(unittest.TestCase):
    def _jpeg_fundo_branco(self, pasta, cor_texto=(10, 10, 10), fundo=(250, 250, 248)):
        im = Image.new("RGB", (400, 600), fundo)
        d = ImageDraw.Draw(im)
        d.rectangle([100, 150, 300, 450], fill=cor_texto)
        d.ellipse([150, 200, 250, 300], fill=fundo)
        p = pasta / "arte.jpg"
        im.save(p, quality=95)
        return p

    def test_ficha_tira_fundo_e_mede(self):
        with tempfile.TemporaryDirectory() as d:
            info, mini = C.ficha_arte(self._jpeg_fundo_branco(Path(d)))
            self.assertEqual(info["fundo_removido"], "sim")
            self.assertAlmostEqual(info["aspecto_arte"], 1.5, delta=0.03)
            self.assertLess(info["tinta_l50"], 15)
            self.assertEqual(C.ink_para_camisa(info), "clara")
            self.assertEqual(len(info["hash_visual"]), 16)

    def test_fichas_com_cache(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._jpeg_fundo_branco(Path(d))
            ok, err = C.fichas([p], Path(d) / "cache", CFG, workers=1)
            self.assertFalse(err)
            self.assertTrue(Path(ok[str(p)]["miniatura"]).exists())
            ok2, _ = C.fichas([p], Path(d) / "cache", CFG, workers=1)
            self.assertEqual(ok2[str(p)]["hash_visual"], ok[str(p)]["hash_visual"])

    def test_similaridade_separa_tinta(self):
        art = sintetico.estampa(120, 160, (240, 240, 240))
        preta = (23, 23, 22)
        foto = Image.new("RGB", (300, 300), preta)
        foto.paste(art.convert("RGB"), (90, 70), art.getchannel("A"))
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "foto.png"
            foto.save(f)
            af = C.assinatura_foto(str(f), (90, 70, 210, 230), preta)
        certa = C.similaridade(af, C.assinatura_arte(art, preta))
        escura = sintetico.estampa(120, 160, (15, 15, 15))
        errada = C.similaridade(af, C.assinatura_arte(escura, preta))
        self.assertGreater(certa, 0.8)
        self.assertGreater(certa - errada, 0.2)


class TestArquivosNovos(unittest.TestCase):
    def test_pistas_pela_pasta(self):
        titulos = {C.chave_titulo("YACHT T-SHIRT"): "YACHT T-SHIRT", C.chave_titulo("MARTINI T-SHIRT"): "MARTINI T-SHIRT"}
        apel = {C.chave_titulo("YATCH T-SHIRT"): "YACHT T-SHIRT"}
        info = {"tem_alpha": "sim", "tinta_l25": "90", "tinta_l50": "95", "tinta_l75": "98", "largura": 10, "altura": 10}
        l = C.classificar_novo("MATERIAL QUALITY 100%/YATCH T-SHIRT/qualquer.png", info, titulos, apel, CFG)
        self.assertEqual((l["produto"], l["lado"], l["para_camisa"], l["tipo"]), ("YACHT T-SHIRT", "costas", "escura", "estampa"))
        l = C.classificar_novo("NOVAS/MARTINI ESTAMPAS/MARTINI FRENTE BRANCA.png", info, titulos, apel, CFG)
        self.assertEqual((l["produto"], l["lado"], l["para_camisa"]), ("MARTINI T-SHIRT", "frente", "clara"))
        l = C.classificar_novo("NOVAS/BRANCA-G-ETIQUETA-IZZY.png", info, titulos, apel, CFG)
        self.assertEqual(l["tipo"], "etiqueta")
        l = C.classificar_novo("NOVAS/arte.cdr", None, titulos, apel, CFG)
        self.assertEqual(l["tipo"], "nao_suportado")

    def test_foto_da_loja(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "8.png"
            sintetico.foto_loja(lado=800).save(p)
            self.assertTrue(C.parece_foto_loja(p))
            q = Path(d) / "arte.png"
            sintetico.estampa(800, 800).save(q)
            self.assertFalse(C.parece_foto_loja(q))

    def test_escanear_ignora_ocultos(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d) / "NOVAS" / "sub"
            base.mkdir(parents=True)
            (base / "a.png").write_bytes(b"x")
            (base / ".DS_Store").write_bytes(b"x")
            (Path(d) / "NOVAS" / ".escondida").mkdir()
            (Path(d) / "NOVAS" / ".escondida" / "b.png").write_bytes(b"x")
            self.assertEqual(C.escanear(Path(d), ["NOVAS", "nao-existe"]), ["NOVAS/sub/a.png"])


class TestComandoCasar(unittest.TestCase):
    """Projeto sintético completo: CSV do Shopify, pastas de artes, inventário, casar pela CLI."""

    def test_ponta_a_ponta(self):
        with tempfile.TemporaryDirectory() as d:
            raiz = Path(d)
            (raiz / "ESTAMPAS PRONTAS P: IZZY" / "SOL ESTAMPAS").mkdir(parents=True)
            (raiz / "NOVAS").mkdir()
            clara = sintetico.estampa(200, 260, (20, 20, 25))
            escura = sintetico.estampa(200, 260, (235, 235, 235))
            clara.save(raiz / "ESTAMPAS PRONTAS P: IZZY" / "SOL ESTAMPAS" / "SOL BRANCA.png")
            escura.save(raiz / "ESTAMPAS PRONTAS P: IZZY" / "SOL ESTAMPAS" / "SOL PRETA.png")
            escura.save(raiz / "NOVAS" / "SOL PRETA - cópia.png")  # duplicata exata
            with open(raiz / "products_export_1.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["Handle", "Title", "Body (HTML)", "Type", "Status", "Option1 Name", "Option1 Value",
                            "Image Src", "Image Position", "Image Alt Text", "Variant Image"])
                w.writerow(["sol", "SOL T-SHIRT", "<p>Estampa nas costas</p>", "T-Shirt", "active", "Cor", "Branca",
                            "", "", "", ""])
                w.writerow(["sol", "", "", "", "", "", "Preta", "", "", "", ""])
                w.writerow(["lua", "LUA T-SHIRT", "<p>Estampa nas costas</p>", "T-Shirt", "active", "Cor", "Preta",
                            "", "", "", ""])
            # inventário: só a versão clara é conhecida; o resto entra pela varredura
            inv = [arte("ESTAMPAS PRONTAS P: IZZY/SOL ESTAMPAS/SOL BRANCA.png", produto="SOL T-SHIRT", l=CLARA)]
            from catalogo import escrever_csv_dicts
            escrever_csv_dicts(raiz / "inventario.csv", C.COLUNAS_INVENTARIO, inv)
            import pallacio
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = pallacio.main(["casar", "--pasta", str(raiz), "--workers", "1"])
            self.assertEqual(rc, 0, buf.getvalue())
            mapa = {(r["handle"], r["cor"], r["lado"]): r for r in ler_csv_dicts(raiz / "mapa.csv")}
            self.assertEqual(len(mapa), 6)
            self.assertEqual(mapa[("sol", "Branca", "costas")]["arquivo_estampa"],
                             "ESTAMPAS PRONTAS P: IZZY/SOL ESTAMPAS/SOL BRANCA.png")
            self.assertEqual(mapa[("sol", "Preta", "costas")]["arquivo_estampa"],
                             "ESTAMPAS PRONTAS P: IZZY/SOL ESTAMPAS/SOL PRETA.png")
            self.assertEqual(mapa[("sol", "Preta", "frente")]["arquivo_estampa"], C.LISO)
            self.assertEqual(mapa[("lua", "Preta", "costas")]["arquivo_estampa"], "")
            self.assertTrue((raiz / "revisao.html").exists())
            novos = ler_csv_dicts(raiz / "inventario_novos.csv")
            dup = [n for n in novos if n["caminho"] == "NOVAS/SOL PRETA - cópia.png"][0]
            self.assertEqual(dup["versao_preferida"], "nao")
            # uma linha marcada como manual sobrevive à próxima rodada
            linhas = ler_csv_dicts(raiz / "mapa.csv")
            for r in linhas:
                if r["handle"] == "lua" and r["lado"] == "costas":
                    r.update({"arquivo_estampa": "NOVAS/SOL PRETA - cópia.png", "origem": "manual"})
            with open(raiz / "mapa.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(linhas[0]))
                w.writeheader()
                w.writerows(linhas)
            with redirect_stdout(io.StringIO()):
                pallacio.main(["casar", "--pasta", str(raiz), "--workers", "1"])
            mapa = {(r["handle"], r["cor"], r["lado"]): r for r in ler_csv_dicts(raiz / "mapa.csv")}
            self.assertEqual(mapa[("lua", "Preta", "costas")]["arquivo_estampa"], "NOVAS/SOL PRETA - cópia.png")


class TestEstamparComFalta(unittest.TestCase):
    def test_linha_sem_arquivo_vira_sem_estampa(self):
        import estampar as E
        from catalogo import LinhaMapa
        from mockups import descobrir_mockups
        from test_estampar import criar_mockups
        with tempfile.TemporaryDirectory() as d:
            raiz = Path(d)
            criar_mockups(raiz / "mockups", close=False, chumbo=False)
            cfg = carregar_config(raiz / "config.json")
            proj = Projeto(raiz, cfg)
            mk = descobrir_mockups(raiz / "mockups", cfg)
            sintetico.estampa().save(raiz / "a.png")
            mapa = [LinhaMapa("x", "X", "Preta", "costas", ""), LinhaMapa("x", "X", "Preta", "frente", "LISO"),
                    LinhaMapa("x", "X", "Branca", "costas", "a.png"), LinhaMapa("x", "X", "Branca", "frente", "LISO")]
            prods = [Produto("x", "X T-SHIRT", "X", "T-Shirt", "active", "", ["Preta", "Branca"])]
            ts = {t.cor: t for t in E.planejar(proj, mapa, mk, prods)}
            self.assertEqual(ts["Preta"].status, "sem_estampa")
            self.assertIn("falta a arte", ts["Preta"].observacao)
            self.assertFalse(ts["Branca"].status)


if __name__ == "__main__":
    unittest.main()
