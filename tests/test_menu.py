import os, tempfile, unittest
from test_crawler import H
import http.server, threading
from crawlforge.menu import Menu
from crawlforge.crawler import Options
from crawlforge import analysis
from crawlforge.cli import build_parser, to_options


def scripted(lines):
    it = iter(lines)
    def inp(prompt=""):
        try: return next(it)
        except StopIteration: raise EOFError
    return inp


class MenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_port}"
    @classmethod
    def tearDownClass(cls): cls.srv.shutdown(); cls.srv.server_close()

    def test_full_flow(self):
        d = tempfile.mkdtemp(); html = os.path.join(d, "r.html"); csvf = os.path.join(d, "r.csv")
        log = []
        m = Menu(Options(rate_limit=0), scripted([
            "1", self.base + "/",                 # target
            "2", "3",                             # deep preset
            "3", "1", "2", "0",                   # depth 2
            "4", "1", "0",                        # toggle JS off then...
            "6", "2", "0", "0",                   # rate limit 0
            "7", "yes",                           # start (authorisation)
            "8", "1", "4", "5", "4", html, "5", "3", csvf, "0",
            "9", "3", "0"]), out=log.append)
        m.run()  # script ends with "0" at the main menu -> clean exit
        self.assertGreater(len(m.results), 3)
        self.assertTrue(os.path.getsize(html) > 500 and os.path.getsize(csvf) > 50)
        with open(html) as fh: self.assertIn("<!doctype html>", fh.read()[:20].lower())
        self.assertTrue(any("endpoints in" in str(x) for x in log))

    def test_refuses_without_authorisation(self):
        m = Menu(Options(urls=[self.base + "/"], rate_limit=0), scripted(["7", "no", "0"]), out=lambda s: None)
        m.run(); self.assertEqual(m.results, [])

    def test_invalid_input_never_crashes(self):
        m = Menu(Options(), scripted(["x", "99", "3", "1", "abc", "0", "5", "5", "0", "0", "6", "1", "-5", "0", "0", "0"]), out=lambda s: None)
        m.run(); self.assertEqual(m.o.depth, 3)


class AnalysisTests(unittest.TestCase):
    R = [{"request": {"endpoint": "http://a.io/api/x?id=1&q=2", "depth": 1}, "response": {"status_code": 500, "content_type": "application/json"}},
         {"request": {"endpoint": "http://a.io/=cmd()", "depth": 0}, "response": {"status_code": 403, "title": "=HYPERLINK(1)"}}]
    def test_params_findings(self):
        self.assertEqual(set(analysis.parameters(self.R)), {"id", "q"})
        f = analysis.findings(self.R); self.assertIn("server errors (5xx)", f); self.assertIn("auth (401/403)", f)
    def test_csv_injection_neutralised(self):
        p = tempfile.mktemp(); analysis.to_csv(self.R, p)
        with open(p) as fh: self.assertIn("'=HYPERLINK", fh.read())
    def test_diff(self):
        new, gone = analysis.diff(self.R[:1], self.R[1:]); self.assertEqual((len(new), len(gone)), (1, 1))
    def test_html_escapes(self):
        p = tempfile.mktemp(); r = [{"request": {"endpoint": "http://a.io/<script>"}, "response": {"title": "<b>x</b>"}}]
        analysis.to_html(r, p)
        with open(p) as fh: self.assertNotIn("<script>", fh.read())

class CliTests(unittest.TestCase):
    def test_preset_and_override(self):
        o = to_options(build_parser().parse_args(["-u", "http://x.io", "-preset", "deep", "-d", "2", "-mc", "200,301"]))
        self.assertEqual(o.depth, 2); self.assertTrue(o.js_crawl and o.secrets); self.assertEqual(o.match_status, [200, 301])

if __name__ == "__main__":
    unittest.main()
