import http.server, json, threading, unittest, tempfile, os
from crawlforge.crawler import Crawler, Options
from crawlforge import extract, filters
from crawlforge.scope import Scope, rdn

PAGES = {
    "/": ("text/html", '<html><title>Home</title><a href="/a">a</a><a href="/b?x=1">b</a><a href="/b?x=2">b2</a>'
          '<img src="/logo.png"><script src="/app.js"></script><a href="https://evil.example.org/x">ext</a>'
          '<form action="/search" method="get"><input name="q"><input type="submit"></form>'
          '<form action="/login" method="post"><input name="u"><input type="password" name="p"></form>'
          '<script>fetch("/api/inline")</script>'),
    "/a": ("text/html", '<title>A</title><a href="/deep/1">1</a>'),
    "/b": ("text/html", "<title>B</title>unique b page content here"),
    "/deep/1": ("text/html", '<title>D</title><a href="/deep/2">2</a>'),
    "/deep/2": ("text/html", "<title>D2</title><a href='/deep/3'>3</a>"),
    "/deep/3": ("text/html", "<title>D3 too deep</title>"),
    "/app.js": ("application/javascript", 'var u="/api/users"; fetch("/api/v2/items"); var k="AKIAABCDEFGHIJKLMNOP";'),
    "/search": ("text/html", "<title>Search</title>results"),
    "/api/users": ("application/json", '{"users":[]}'),
    "/api/v2/items": ("application/json", '{"items":[]}'),
    "/api/inline": ("application/json", '{"ok":1}'),
    "/robots.txt": ("text/plain", "User-agent: *\nDisallow: /secret-admin/\nSitemap: {base}/sitemap.xml\n"),
    "/sitemap.xml": ("application/xml", "<urlset><url><loc>{base}/from-sitemap</loc></url></urlset>"),
    "/from-sitemap": ("text/html", "<title>S</title>"),
    "/secret-admin/": ("text/html", "<title>Admin</title>"),
}


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        path = self.path.split("?")[0]
        if path in PAGES:
            ct, body = PAGES[path]
            body = body.replace("{base}", f"http://127.0.0.1:{self.server.server_port}")
            if path == "/search": body += self.path  # query-dependent body so content-dedup keeps it
            body = body.encode()
            self.send_response(200); self.send_header("Content-Type", ct)
            self.send_header("Server", "nginx"); self.end_headers(); self.wfile.write(body)
        else:
            self.send_response(404); self.end_headers(); self.wfile.write(b"nf")
    def do_POST(self):
        raise AssertionError("crawler must never POST by itself")


class CrawlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_port}"

    @classmethod
    def tearDownClass(cls): cls.srv.shutdown(); cls.srv.server_close()

    def crawl(self, **kw):
        o = Options(urls=[self.base + "/"], rate_limit=0, silent=True, **kw)
        c = Crawler(o, emit=lambda r: None)
        return {r["request"]["endpoint"].replace(self.base, ""): r for r in c.run()}

    def test_basic_and_depth(self):
        r = self.crawl(depth=3)
        self.assertIn("/a", r); self.assertIn("/deep/1", r); self.assertIn("/deep/2", r)
        self.assertNotIn("/deep/3", r)           # depth limit
        self.assertNotIn("/logo.png", r)         # default ext filter
        self.assertFalse(any("evil.example.org" in u for u in r))  # out of scope

    def test_js_crawl(self):
        self.assertNotIn("/api/users", self.crawl())
        r = self.crawl(js_crawl=True)
        for p in ("/api/users", "/api/v2/items", "/api/inline"): self.assertIn(p, r)

    def test_known_files(self):
        r = self.crawl(known_files=True)
        self.assertIn("/secret-admin/", r); self.assertIn("/from-sitemap", r)

    def test_bfs_same_set(self):
        strip = lambda d: {u.split("?")[0] for u in d}  # /b?x=1 and /b?x=2 have identical bodies; dedup keeps either
        self.assertEqual(strip(self.crawl(strategy="breadth-first")), strip(self.crawl(strategy="depth-first")))

    def test_ignore_query_params(self):
        r = self.crawl(ignore_query_params=True)
        self.assertEqual(len([u for u in r if u.startswith("/b")]), 1)

    def test_forms_autofill_never_posts(self):
        r = self.crawl(form_extraction=True, auto_form_fill=True)
        self.assertIn("/search?q=test", r)
        self.assertEqual(len(r["/"]["response"]["forms"]), 2)

    def test_tech_and_secrets(self):
        r = self.crawl(tech_detect=True, secrets=True, js_crawl=True)
        self.assertIn("nginx", r["/"]["response"]["technologies"])
        self.assertEqual(r["/app.js"]["response"]["secrets"][0]["type"], "aws-access-key-id")

    def test_max_domain_pages(self):
        self.assertLessEqual(len(self.crawl(max_domain_pages=3)), 3)

    def test_resume_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            st = os.path.join(d, "state.json")
            c = Crawler(Options(urls=[self.base + "/"], rate_limit=0, resume=st, concurrency=1), emit=lambda r: None)
            c.enqueue(self.base + "/", 0); c.stop.set(); c._save_state()
            self.assertTrue(os.path.exists(st))
            c2 = Crawler(Options(urls=[self.base + "/"], rate_limit=0, resume=st), emit=lambda r: None)
            self.assertTrue(c2._load_state())

    def test_match_filter_regex(self):
        r = self.crawl(match_regex=[r"/deep/"])
        self.assertTrue(r and all("/deep/" in u for u in r))


class UnitTests(unittest.TestCase):
    def test_scope(self):
        s = Scope(["https://www.example.com/"], "rdn")
        self.assertTrue(s.allowed("https://api.example.com/x")); self.assertFalse(s.allowed("https://example.org/"))
        self.assertFalse(Scope(["https://www.example.com/"], "fqdn").allowed("https://api.example.com/"))
        self.assertFalse(Scope(["https://a.example.com/"], "rdn", out_scope=[r"/logout"]).allowed("https://a.example.com/logout"))
        self.assertEqual(rdn("a.b.example.co.uk"), "example.co.uk")

    def test_similar(self):
        f = filters.SimilarURLFilter(3)
        res = [f.allow(f"http://x.io/users/{i}") for i in range(6)]
        self.assertEqual(res, [True, True, True, False, False, False])

    def test_simhash_near_dup(self):
        d = filters.ContentDeduper(similar=True, distance=6)
        base = " ".join(f"word{i}" for i in range(200))
        self.assertFalse(d.is_duplicate(base)); self.assertTrue(d.is_duplicate(base + " extra"))

    def test_normalize(self):
        self.assertEqual(filters.normalize("HTTP://Example.com:80/a#frag"), "http://example.com/a")

    def test_secret_masking(self):
        m = extract.find_secrets("k=AKIAABCDEFGHIJKLMNOP")[0]["match"]
        self.assertNotIn("ABCDEFGHIJKLMN", m)

if __name__ == "__main__":
    unittest.main()
