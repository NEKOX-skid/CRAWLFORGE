import http.client, http.server, json, threading, time, unittest
from test_crawler import H
from crawlforge.web import make_server, build_options


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.site = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.site.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.site.server_port}"
        cls.web, cls.token = make_server("127.0.0.1", 0)
        threading.Thread(target=cls.web.serve_forever, daemon=True).start()
        cls.port = cls.web.server_port

    @classmethod
    def tearDownClass(cls):
        for s in (cls.site, cls.web): s.shutdown(); s.server_close()

    def req(self, method, path, body=None, cookie=True, host=None, ctype="application/json"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": host or f"127.0.0.1:{self.port}"}
        if cookie: h["Cookie"] = f"cf_token={self.token}"
        data = None
        if body is not None: data = json.dumps(body); h["Content-Type"] = ctype
        c.request(method, path, data, h); r = c.getresponse(); raw = r.read(); c.close()
        return r.status, raw, r

    def jreq(self, *a, **k):
        s, raw, _ = self.req(*a, **k); return s, json.loads(raw)

    def start(self, **kw):
        return self.jreq("POST", "/api/jobs", {"urls": [self.base + "/"], "authorised": True, "rate_limit": 0, **kw})

    def wait(self, jid):
        for _ in range(100):
            s, v = self.jreq("GET", f"/api/jobs/{jid}")
            if v["status"] != "running": return v
            time.sleep(0.1)
        self.fail("job did not finish")

    def test_auth_and_host_checks(self):
        self.assertEqual(self.req("GET", "/", cookie=False)[0], 401)
        self.assertEqual(self.req("GET", "/api/presets", cookie=False)[0], 401)
        self.assertEqual(self.req("GET", "/api/presets", host="evil.example:80")[0], 403)   # DNS-rebinding guard
        s, _, r = self.req("GET", f"/?t={self.token}", cookie=False)
        self.assertEqual(s, 302); self.assertIn("HttpOnly", r.getheader("Set-Cookie")); self.assertIn("SameSite=Strict", r.getheader("Set-Cookie"))
        self.assertEqual(self.req("GET", "/?t=wrong", cookie=False)[0], 401)
        s, raw, r = self.req("GET", "/"); self.assertEqual(s, 200); self.assertIn(b"Crawlforge", raw)
        self.assertIn("default-src 'self'", r.getheader("Content-Security-Policy"))

    def test_post_requirements(self):
        self.assertEqual(self.req("POST", "/api/jobs", {"urls": ["x"]}, ctype="text/plain")[0], 415)
        self.assertEqual(self.start(authorised=False)[0], 400)
        self.assertEqual(self.jreq("POST", "/api/jobs", {"urls": [], "authorised": True})[0], 400)
        self.assertEqual(self.start(out_scope=["("])[0], 400)           # bad regex
        self.assertEqual(self.start(proxy="file:///etc/passwd")[0], 400)
        self.assertEqual(self.start(match_status=["200"])[0], 400)

    def test_option_whitelist_and_clamp(self):
        o = build_options({"urls": ["a.io"], "concurrency": 9999, "depth": -4, "output": "/etc/x", "resume": "/tmp/y", "store_response_dir": "/tmp/z"})
        self.assertEqual((o.concurrency, o.depth), (50, 0)); self.assertEqual((o.output, o.resume, o.store_response_dir), ("", "", ""))

    def test_full_job_and_exports(self):
        s, j = self.start(depth=3, js_crawl=True, tech_detect=True, secrets=True); self.assertEqual(s, 200)
        v = self.wait(j["id"]); self.assertEqual(v["status"], "done"); self.assertGreater(v["total"], 5)
        s, v2 = self.jreq("GET", f"/api/jobs/{j['id']}?since={v['total'] - 1}"); self.assertEqual(len(v2["records"]), 1)
        s, a = self.jreq("GET", f"/api/jobs/{j['id']}/analysis")
        self.assertIn("secrets", a["findings"]); self.assertIn("200", a["summary"]["status"])
        for fmt, needle in (("csv", b"url,method"), ("html", b"<!doctype html>"), ("jsonl", b'"request"'), ("txt", b"http://")):
            s, raw, r = self.req("GET", f"/api/jobs/{j['id']}/export?fmt={fmt}")
            self.assertEqual(s, 200); self.assertIn(needle, raw); self.assertIn("attachment", r.getheader("Content-Disposition"))
        self.assertEqual(self.req("GET", f"/api/jobs/{j['id']}/export?fmt=exe")[0], 400)
        self.assertEqual(self.req("GET", "/api/jobs/../../etc/passwd")[0], 404)

    def test_stop(self):
        s, j = self.start(depth=10, delay=0.5, concurrency=1)
        self.assertEqual(self.jreq("POST", f"/api/jobs/{j['id']}/stop", {})[0], 200)
        self.assertEqual(self.wait(j["id"])["status"], "stopped")

if __name__ == "__main__":
    unittest.main()
