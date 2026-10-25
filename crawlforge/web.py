"""Local web app: stdlib HTTP server + JSON API + single-page UI. Binds to loopback by default.

Security model: random per-run token (cookie, SameSite=Strict), Host-header allow-list (anti DNS-rebinding),
JSON-only POSTs (anti form CSRF), whitelisted/clamped options, no filesystem options, explicit authorisation flag.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import __version__, analysis
from .crawler import Crawler, Options
from .presets import PRESETS

MAX_RECORDS, MAX_JOBS, MAX_BODY = 50_000, 20, 64 * 1024
INTS = {"depth": (0, 10), "concurrency": (1, 50), "rate_limit": (0, 1000), "host_rate_limit": (0, 1000), "timeout": (1, 120),
        "retries": (0, 5), "max_domain_pages": (0, 100_000), "filter_similar_threshold": (1, 1000), "content_similar_distance": (0, 32)}
FLOATS = {"delay": (0, 30), "crawl_duration": (0, 86_400)}
BOOLS = ["js_crawl", "known_files", "path_climb", "form_extraction", "auto_form_fill", "tech_detect", "secrets", "content_similar",
         "filter_similar", "ignore_query_params", "no_scope", "display_out_scope", "disable_redirects", "verify_tls", "no_default_ext_filter"]
STR_LISTS = ["ext_match", "ext_filter", "in_scope", "out_scope", "match_regex", "filter_regex", "headers"]
INT_LISTS = ["match_status", "filter_status"]
RX_LISTS = {"in_scope", "out_scope", "match_regex", "filter_regex"}


def build_options(d: dict) -> Options:
    """Whitelist + clamp every field. Raises ValueError with a user-facing message."""
    o = Options(rate_limit=150, silent=True)
    urls = d.get("urls", [])
    if not isinstance(urls, list) or not 1 <= len(urls) <= 20 or not all(isinstance(u, str) and 0 < len(u) < 2048 for u in urls):
        raise ValueError("provide 1-20 target URLs")
    o.urls = [u.strip() for u in urls]
    for k, (lo, hi) in INTS.items():
        if k in d:
            if not isinstance(d[k], (int, float)) or isinstance(d[k], bool): raise ValueError(f"{k} must be a number")
            setattr(o, k, int(min(max(d[k], lo), hi)))
    for k, (lo, hi) in FLOATS.items():
        if k in d:
            if not isinstance(d[k], (int, float)) or isinstance(d[k], bool): raise ValueError(f"{k} must be a number")
            setattr(o, k, float(min(max(d[k], lo), hi)))
    for k in BOOLS:
        if k in d: setattr(o, k, bool(d[k]))
    if d.get("strategy") in ("depth-first", "breadth-first"): o.strategy = d["strategy"]
    fs = d.get("field_scope", "rdn")
    if not isinstance(fs, str) or len(fs) > 200: raise ValueError("bad field_scope")
    if fs not in ("rdn", "dn", "fqdn"):
        try: re.compile(fs)
        except re.error: raise ValueError("field_scope is not a valid regex")
    o.field_scope = fs
    if isinstance(d.get("proxy"), str) and d["proxy"].strip():
        if not re.match(r"^https?://[^\s]+$", d["proxy"].strip()): raise ValueError("proxy must be http(s)://host:port")
        o.proxy = d["proxy"].strip()
    for k in STR_LISTS:
        v = d.get(k, [])
        if not isinstance(v, list) or len(v) > 50 or not all(isinstance(x, str) and len(x) < 500 for x in v): raise ValueError(f"{k} must be a list of strings")
        v = [x.strip() for x in v if x.strip()]
        if k in RX_LISTS:
            for x in v:
                try: re.compile(x)
                except re.error: raise ValueError(f"invalid regex in {k}: {x}")
        setattr(o, k, v)
    for k in INT_LISTS:
        v = d.get(k, [])
        if not isinstance(v, list) or not all(isinstance(x, int) and 100 <= x <= 599 for x in v): raise ValueError(f"{k} must be status codes")
        setattr(o, k, v)
    return o  # jsonl/output/resume/store_response_dir deliberately untouched: the web API never writes to disk


class Job:
    def __init__(self, opts: Options):
        self.id, self.records, self.status, self.error = uuid.uuid4().hex[:12], [], "running", ""
        self.t0, self.t1, self.lock, self.stopped = time.time(), None, threading.Lock(), False
        self.c = Crawler(opts, emit=self._emit)
        threading.Thread(target=self._run, daemon=True).start()

    def _emit(self, rec):
        with self.lock:
            self.records.append(rec)
            if len(self.records) >= MAX_RECORDS: self.c.stop.set()

    def _run(self):
        try: self.c.run()
        except Exception as e: self.error = f"{type(e).__name__}: {e}"
        self.t1 = time.time()
        self.status = "stopped" if self.stopped else ("error" if self.error else "done")

    def stop(self):
        self.stopped = True
        self.c.stop.set()
        with self.c.cv: self.c.cv.notify_all()

    def view(self, since: int):
        with self.lock: new = self.records[since:since + 500]; total = len(self.records)
        return {"id": self.id, "status": self.status, "error": self.error, "total": total, "next": since + len(new),
                "fetched": self.c.fetched, "queued": len(self.c.frontier), "elapsed": round((self.t1 or time.time()) - self.t0, 1), "records": new}


class State:
    def __init__(self, host: str, port: int, token: str):
        self.token, self.jobs, self.lock = token, {}, threading.Lock()
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}", f"{host}:{port}"}


def make_handler(st: State):
    class H(BaseHTTPRequestHandler):
        server_version = "Crawlforge"
        def log_message(self, *a): pass

        def _send(self, code, body: bytes, ctype="application/json", extra=None):
            self.send_response(code)
            for k, v in {"Content-Type": ctype, "Content-Length": str(len(body)), "Cache-Control": "no-store",
                         "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
                         "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; frame-ancestors 'none'",
                         **(extra or {})}.items():
                self.send_header(k, v)
            self.end_headers(); self.wfile.write(body)

        def _json(self, code, obj): self._send(code, json.dumps(obj).encode())
        def _err(self, code, msg): self._json(code, {"error": msg})

        def _authed(self) -> bool:
            if self.headers.get("Host", "") not in st.hosts: self._err(403, "bad host"); return False
            ck = dict(c.strip().partition("=")[::2] for c in self.headers.get("Cookie", "").split(";") if "=" in c)
            if not secrets.compare_digest(ck.get("cf_token", ""), st.token): self._err(401, "open the URL printed in the terminal"); return False
            return True

        def do_GET(self):
            u = urlsplit(self.path); q = parse_qs(u.query)
            if u.path == "/" and "t" in q and self.headers.get("Host", "") in st.hosts:
                if secrets.compare_digest(q["t"][0], st.token):
                    return self._send(302, b"", "text/plain", {"Location": "/", "Set-Cookie": f"cf_token={st.token}; HttpOnly; SameSite=Strict; Path=/"})
                return self._err(401, "bad token")
            if not self._authed(): return
            if u.path == "/":
                with open(os.path.join(os.path.dirname(__file__), "static", "index.html"), "rb") as fh:
                    return self._send(200, fh.read(), "text/html; charset=utf-8")
            if u.path == "/api/presets":
                from dataclasses import fields
                return self._json(200, {"version": __version__, "presets": {k: {"description": d, "options": o} for k, (d, o) in PRESETS.items()}})
            m = re.fullmatch(r"/api/jobs/([0-9a-f]{12})(?:/(analysis|export))?", u.path)
            job = st.jobs.get(m.group(1)) if m else None
            if not m or not job: return self._err(404, "not found")
            if not m.group(2):
                try: since = max(0, int(q.get("since", ["0"])[0]))
                except ValueError: since = 0
                return self._json(200, job.view(since))
            with job.lock: recs = list(job.records)
            if m.group(2) == "analysis":
                return self._json(200, {"summary": analysis.summarize(recs), "params": dict(list(analysis.parameters(recs).items())[:200]),
                                        "findings": {k: v[:200] for k, v in analysis.findings(recs).items()}})
            fmt = q.get("fmt", ["txt"])[0]
            fn = {"txt": analysis.to_txt, "jsonl": analysis.to_jsonl, "csv": analysis.to_csv, "html": analysis.to_html}.get(fmt)
            if not fn: return self._err(400, "fmt must be txt|jsonl|csv|html")
            with tempfile.TemporaryDirectory() as d:
                p = os.path.join(d, "x"); fn(recs, p)
                with open(p, "rb") as fh: data = fh.read()
            ct = {"html": "text/html", "csv": "text/csv", "jsonl": "application/x-ndjson", "txt": "text/plain"}[fmt]
            self._send(200, data, ct + "; charset=utf-8", {"Content-Disposition": f'attachment; filename="crawlforge-{job.id}.{fmt}"'})

        def do_POST(self):
            if not self._authed(): return
            if not self.headers.get("Content-Type", "").startswith("application/json"): return self._err(415, "JSON only")
            try:
                n = int(self.headers.get("Content-Length", "0"))
                if not 0 < n <= MAX_BODY: return self._err(413, "bad size")
                body = json.loads(self.rfile.read(n))
                if not isinstance(body, dict): raise ValueError("body must be an object")
            except (ValueError, json.JSONDecodeError) as e:
                return self._err(400, f"bad JSON: {e}")
            m = re.fullmatch(r"/api/jobs/([0-9a-f]{12})/stop", self.path)
            if m:
                job = st.jobs.get(m.group(1))
                if not job: return self._err(404, "not found")
                job.stop(); return self._json(200, {"ok": True})
            if self.path != "/api/jobs": return self._err(404, "not found")
            if body.get("authorised") is not True: return self._err(400, "you must confirm you are authorised to test these targets")
            try: opts = build_options(body)
            except ValueError as e: return self._err(400, str(e))
            with st.lock:
                if sum(j.status == "running" for j in st.jobs.values()) >= 3: return self._err(429, "3 crawls already running")
                while len(st.jobs) >= MAX_JOBS:
                    st.jobs.pop(next(iter(st.jobs)))
                job = Job(opts); st.jobs[job.id] = job
            self._json(200, {"id": job.id})
    return H


def make_server(host="127.0.0.1", port=8787):
    token = secrets.token_urlsafe(24)
    httpd = ThreadingHTTPServer((host, port), None)
    st = State(host, httpd.server_port, token)
    httpd.RequestHandlerClass = make_handler(st)
    httpd.state = st
    return httpd, token


def serve(host="127.0.0.1", port=8787, open_browser=True):
    httpd, token = make_server(host, port)
    url = f"http://{host}:{httpd.server_port}/?t={token}"
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("WARNING: listening on a non-loopback address. Anyone who can reach this port AND has the token can launch crawls.")
    print(f"Crawlforge web UI  ->  {url}\n(Ctrl-C to stop)")
    if open_browser:
        try: webbrowser.open(url)
        except Exception: pass
    try: httpd.serve_forever()
    except KeyboardInterrupt: print("\nbye.")
    return 0
