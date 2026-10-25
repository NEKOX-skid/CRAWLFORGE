"""Crawl engine: threaded frontier (DFS/BFS), scope, filters, extraction, output, resume."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from urllib.parse import urlencode, urlsplit, urlunsplit

from . import extract, filters
from .http import Client, RateLimiter
from .scope import Scope, hostname

TEXTUAL = ("text/", "application/json", "application/xml", "application/javascript",
           "application/x-javascript", "application/xhtml", "application/rss", "application/atom")


@dataclass
class Options:
    urls: list = field(default_factory=list)
    depth: int = 3
    strategy: str = "depth-first"          # or breadth-first
    concurrency: int = 10
    rate_limit: int = 150
    host_rate_limit: int = 0
    delay: float = 0.0
    timeout: int = 10
    retries: int = 1
    proxy: str = ""
    headers: list = field(default_factory=list)
    max_response_size: int = 4 * 1024 * 1024
    disable_redirects: bool = False
    verify_tls: bool = False
    # scope
    field_scope: str = "rdn"
    in_scope: list = field(default_factory=list)
    out_scope: list = field(default_factory=list)
    no_scope: bool = False
    display_out_scope: bool = False
    # discovery
    js_crawl: bool = False
    known_files: bool = False               # robots.txt + sitemap.xml
    path_climb: bool = False
    form_extraction: bool = False
    auto_form_fill: bool = False            # GET forms only (never auto-submits POST)
    tech_detect: bool = False
    secrets: bool = False
    # filters
    ext_match: list = field(default_factory=list)
    ext_filter: list = field(default_factory=list)
    no_default_ext_filter: bool = False
    match_regex: list = field(default_factory=list)
    filter_regex: list = field(default_factory=list)
    match_status: list = field(default_factory=list)
    filter_status: list = field(default_factory=list)
    ignore_query_params: bool = False
    filter_similar: bool = False
    filter_similar_threshold: int = 10
    content_dedup: bool = True
    content_similar: bool = False
    content_similar_distance: int = 3
    # limits
    crawl_duration: float = 0.0
    max_domain_pages: int = 0
    # output
    jsonl: bool = False
    output: str = ""
    store_response_dir: str = ""
    omit_body: bool = True
    resume: str = ""
    silent: bool = False
    verbose: bool = False


class Crawler:
    def __init__(self, opts: Options, emit=None):
        self.o = opts
        self.seeds = [self._seed(u) for u in opts.urls if u.strip()]
        self.scope = Scope(self.seeds, opts.field_scope, opts.in_scope, opts.out_scope, opts.no_scope)
        self.client = Client(opts.timeout, opts.retries, opts.proxy, opts.headers, opts.max_response_size,
                             not opts.disable_redirects, opts.verify_tls,
                             RateLimiter(opts.rate_limit, opts.host_rate_limit, opts.delay))
        self.similar = filters.SimilarURLFilter(opts.filter_similar_threshold) if opts.filter_similar else None
        self.dedup = filters.ContentDeduper(opts.content_similar, opts.content_similar_distance)
        self.ext_filter = set() if opts.no_default_ext_filter else set(filters.DEFAULT_EXT_FILTER)
        self.ext_filter |= {e.lower().lstrip(".") for e in opts.ext_filter}
        self.ext_match = {e.lower().lstrip(".") for e in opts.ext_match}
        self.match_rx = [re.compile(p) for p in opts.match_regex]
        self.filter_rx = [re.compile(p) for p in opts.filter_regex]
        self.emit = emit or self._default_emit
        self.frontier: deque = deque()
        self.cv = threading.Condition()
        self.pending = 0
        self.seen: set[str] = set()
        self.page_counts: dict[str, int] = {}
        self.results: list[dict] = []
        self.stop = threading.Event()
        self.deadline = time.monotonic() + opts.crawl_duration if opts.crawl_duration else None
        self.out_lock = threading.Lock()
        self.out_fh = open(opts.output, "a", encoding="utf-8") if opts.output else None
        self.fetched = 0

    # ----------------------------------------------------------------------- helpers
    @staticmethod
    def _seed(u: str) -> str:
        u = u.strip()
        return filters.normalize(u if "://" in u else "https://" + u)

    def _log(self, msg):
        if self.o.verbose and not self.o.silent:
            print(f"[inf] {msg}", file=__import__("sys").stderr)

    def _default_emit(self, rec: dict):
        line = json.dumps(rec, ensure_ascii=False) if self.o.jsonl else rec["request"]["endpoint"]
        with self.out_lock:
            print(line, flush=True)
            if self.out_fh:
                self.out_fh.write(line + "\n")
                self.out_fh.flush()

    def _output_ok(self, url: str, status: int = 0) -> bool:
        if self.o.match_status and status not in self.o.match_status:
            return False
        if status in self.o.filter_status:
            return False
        ext = filters.extension(url)
        if self.ext_match and (ext or "none") not in self.ext_match:
            return False
        if ext in self.ext_filter:
            return False
        if self.match_rx and not any(r.search(url) for r in self.match_rx):
            return False
        if any(r.search(url) for r in self.filter_rx):
            return False
        return True

    # ----------------------------------------------------------------------- frontier
    def enqueue(self, url, depth, method="GET", tag="", attr="", source="", data=None):
        url = filters.normalize(url)
        if not url or urlsplit(url).scheme not in ("http", "https"):
            return
        if not self.scope.allowed(url):
            if self.o.display_out_scope and not self.o.silent:
                with self.out_lock:
                    print(url, flush=True)
            return
        ext = filters.extension(url)
        if ext in self.ext_filter and url not in self.seeds:
            return
        if self.similar and not self.similar.allow(url):
            return
        key = filters.dedup_key(method, url, self.o.ignore_query_params)
        host = hostname(url)
        with self.cv:
            if key in self.seen or self.stop.is_set():
                return
            if self.o.max_domain_pages and self.page_counts.get(host, 0) >= self.o.max_domain_pages:
                return
            self.seen.add(key)
            self.page_counts[host] = self.page_counts.get(host, 0) + 1
            self.pending += 1
            self.frontier.append((url, depth, method, tag, attr, source, data))
            self.cv.notify()

    def _next(self):
        with self.cv:
            while True:
                if self.stop.is_set():
                    return None
                if self.frontier:
                    return self.frontier.pop() if self.o.strategy == "depth-first" else self.frontier.popleft()
                if self.pending == 0:
                    return None
                self.cv.wait(0.2)
                if self.deadline and time.monotonic() > self.deadline:
                    self.stop.set()
                    self.cv.notify_all()

    def _done(self):
        with self.cv:
            self.pending -= 1
            if self.pending <= 0 or self.stop.is_set():
                self.cv.notify_all()

    # ----------------------------------------------------------------------- worker
    def _worker(self):
        while True:
            item = self._next()
            if item is None:
                return
            try:
                self._process(*item)
            except Exception as e:  # never let one URL kill the crawl
                self._log(f"error processing {item[0]}: {type(e).__name__}: {e}")
            finally:
                self._done()
                if self.deadline and time.monotonic() > self.deadline:
                    self.stop.set()

    def _process(self, url, depth, method, tag, attr, source, data):
        resp = self.client.request(url, method, data)
        self.fetched += 1
        if resp.error:
            self._log(f"{url}: {resp.error}")
            return
        ctype = resp.content_type
        is_text = ctype.startswith(TEXTUAL) or ctype == "" or url.endswith((".js", ".xml", ".txt"))
        body = resp.text if is_text else ""

        if body and self.dedup and self.o.content_dedup and self.dedup.is_duplicate(body):
            return  # identical/near-identical page: don't output or parse again

        page = None
        links: list[tuple[str, str, str]] = []
        forms: list[dict] = []
        title = ""
        if body and ("html" in ctype or ctype == "" or "xhtml" in ctype):
            page = extract.parse_html(body, resp.final_url or url)
            links, forms, title = page.links, page.forms, page.title
            if self.o.js_crawl:
                for js in page.inline_js:
                    links += [(u, "script", "inline") for u in extract.js_endpoints(js, url)]
        elif body and ("javascript" in ctype or urlsplit(url).path.endswith(".js")):
            if self.o.js_crawl:
                links += [(u, "js", "endpoint") for u in extract.js_endpoints(body, url)]
        elif body and ("xml" in ctype and "sitemap" in url.lower()):
            links += [(u, "sitemap", "loc") for u in extract.parse_sitemap(body)]
        if resp.status in (301, 302, 303, 307, 308) and resp.headers.get("location"):
            from urllib.parse import urljoin
            links.append((urljoin(url, resp.headers["location"]), "header", "location"))

        rec = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "request": {"method": method, "endpoint": url, "tag": tag, "attribute": attr, "source": source, "depth": depth},
            "response": {"status_code": resp.status, "content_type": ctype, "content_length": len(resp.body),
                         "title": title},
        }
        if self.o.tech_detect:
            rec["response"]["technologies"] = extract.detect_tech(resp.headers, body)
        if self.o.form_extraction and forms:
            rec["response"]["forms"] = forms
        if self.o.secrets and body:
            s = extract.find_secrets(body)
            if s:
                rec["response"]["secrets"] = s
        if not self.o.omit_body:
            rec["response"]["body"] = body
        if self.o.store_response_dir:
            self._store(rec, resp)

        if self._output_ok(url, resp.status):
            self.results.append(rec)
            self.emit(rec)

        # ---- follow discovered links
        if depth >= self.o.depth:
            return
        for u, t, a in links:
            self.enqueue(u, depth + 1, "GET", t, a, url)
        for f in forms:
            self._handle_form(f, depth, url)
        if self.o.path_climb:
            p = urlsplit(url)
            parts = [s for s in p.path.split("/") if s][:-1]
            for i in range(len(parts), 0, -1):
                self.enqueue(urlunsplit((p.scheme, p.netloc, "/" + "/".join(parts[:i]) + "/", "", "")),
                             depth + 1, "GET", "path-climb", "", url)

    def _handle_form(self, f: dict, depth: int, source: str):
        if f["method"] == "GET":
            self.enqueue(f["action"], depth + 1, "GET", "form", "action", source)
            if self.o.auto_form_fill and f["fields"]:
                q = {}
                for fld in f["fields"]:
                    t = fld["type"].lower()
                    if t in ("submit", "button", "reset", "file", "password"):
                        continue
                    q[fld["name"]] = fld["value"] or {"email": "test@example.com", "number": "1",
                                                       "tel": "5555550100", "url": "https://example.com"}.get(t, "test")
                if q:
                    sp = urlsplit(f["action"])
                    self.enqueue(urlunsplit((sp.scheme, sp.netloc, sp.path, urlencode(q), "")),
                                 depth + 1, "GET", "form", "autofill", source)
        else:
            # POST forms are reported (with -fx) but never auto-submitted: submitting can mutate server state.
            self._log(f"POST form not submitted: {f['action']}")

    def _store(self, rec, resp):
        os.makedirs(self.o.store_response_dir, exist_ok=True)
        import hashlib
        name = hashlib.sha1(rec["request"]["endpoint"].encode()).hexdigest()
        with open(os.path.join(self.o.store_response_dir, name + ".txt"), "w", encoding="utf-8") as fh:
            fh.write(f'{rec["request"]["method"]} {rec["request"]["endpoint"]}\n')
            fh.write(f"HTTP {resp.status}\n")
            for k, v in resp.headers.items():
                fh.write(f"{k}: {v}\n")
            fh.write("\n" + resp.text)

    # ----------------------------------------------------------------------- state / resume
    def _save_state(self):
        if not self.o.resume:
            return
        with self.cv:
            state = {"seen": sorted(self.seen), "frontier": list(self.frontier)}
        with open(self.o.resume, "w", encoding="utf-8") as fh:
            json.dump(state, fh)

    def _load_state(self) -> bool:
        if not (self.o.resume and os.path.exists(self.o.resume)):
            return False
        with open(self.o.resume, encoding="utf-8") as fh:
            state = json.load(fh)
        self.seen = set(state.get("seen", []))
        for it in state.get("frontier", []):
            self.frontier.append(tuple(it))
            self.pending += 1
        self._log(f"resumed with {len(self.frontier)} queued URLs")
        return bool(self.frontier)

    # ----------------------------------------------------------------------- run
    def run(self) -> list[dict]:
        resumed = self._load_state()
        if not resumed:
            for s in self.seeds:
                self.enqueue(s, 0, source="seed")
                if self.o.known_files:
                    p = urlsplit(s)
                    base = f"{p.scheme}://{p.netloc}"
                    r = self.client.request(base + "/robots.txt")
                    if r.status == 200:
                        paths, sitemaps = extract.parse_robots(r.text, base)
                        for u in paths:
                            self.enqueue(u, 1, "GET", "robots", "", base + "/robots.txt")
                        for u in sitemaps:
                            self.enqueue(u, 1, "GET", "sitemap", "", base + "/robots.txt")
                    self.enqueue(base + "/sitemap.xml", 1, "GET", "sitemap", "", base)
        threads = [threading.Thread(target=self._worker, daemon=True) for _ in range(max(1, self.o.concurrency))]
        for t in threads:
            t.start()
        try:
            while any(t.is_alive() for t in threads):
                time.sleep(0.1)
        except KeyboardInterrupt:
            self.stop.set()
            with self.cv:
                self.cv.notify_all()
            for t in threads:
                t.join(timeout=2)
        if self.stop.is_set() or self.frontier:
            self._save_state()
        elif self.o.resume and os.path.exists(self.o.resume):
            os.remove(self.o.resume)  # finished cleanly
        if self.out_fh:
            self.out_fh.close()
        return self.results
