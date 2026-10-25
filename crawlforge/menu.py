"""Interactive numbered menu (select 1-9, 0 to go back/exit)."""
from __future__ import annotations

import dataclasses
import json
import os
import sys
import threading
import time

from . import __version__, analysis
from .crawler import Crawler, Options
from .presets import PRESETS, apply

BANNER = r"""
  ╔═╗┬─┐┌─┐┬ ┬┬  ╔═╗┌─┐┬─┐┌─┐┌─┐
  ║  ├┬┘├─┤││││  ╠╣ │ │├┬┘│ ┬├┤
  ╚═╝┴└─┴ ┴└┴┘┴─┘╚  └─┘┴└─└─┘└─┘  v{v}
  Only crawl targets you own or are authorised to test.
"""

TOGGLES = [("js_crawl", "JavaScript endpoint parsing"), ("known_files", "robots.txt + sitemap.xml"),
           ("path_climb", "Path climb (parent dirs)"), ("form_extraction", "Extract forms"),
           ("auto_form_fill", "Auto-fill & follow GET forms"), ("tech_detect", "Technology detection"),
           ("secrets", "Secret pattern detection (masked)"), ("content_similar", "Near-duplicate page filter"),
           ("filter_similar", "Similar-URL filter (/id/1, /id/2 ...)")]


class Menu:
    def __init__(self, opts: Options | None = None, inp=input, out=print):
        self.o = opts or Options()
        self.inp, self.out = inp, out
        self.results: list[dict] = []
        self.authorised = False

    # ------------------------------------------------------------------ io helpers
    def ask(self, prompt: str, default: str = "") -> str:
        try:
            v = self.inp(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
        except EOFError:
            raise SystemExit(0)
        return v or default

    def ask_int(self, prompt: str, default: int, lo: int = 0, hi: int = 10**9) -> int:
        v = self.ask(prompt, str(default))
        try:
            n = int(v)
        except ValueError:
            self.out("  ! not a number, unchanged"); return default
        if not lo <= n <= hi:
            self.out(f"  ! must be {lo}..{hi}, unchanged"); return default
        return n

    def csv(self, v: str) -> list[str]:
        return [x.strip() for x in v.split(",") if x.strip()]

    def show(self, title: str, items: list[str]):
        self.out(f"\n== {title} ==")
        for it in items:
            self.out("  " + it)

    # ------------------------------------------------------------------ main loop
    def run(self):
        self.out(BANNER.format(v=__version__))
        actions = {"1": self.targets, "2": self.presets, "3": self.scope, "4": self.features, "5": self.filters,
                   "6": self.network, "7": self.start, "8": self.results_menu, "9": self.profiles}
        while True:
            self.status_line()
            self.show("MAIN MENU", ["1) Target(s)", "2) Scan presets", "3) Scope & depth", "4) Features (on/off)",
                                    "5) Filters & limits", "6) Network & rate limits", "7) START crawl",
                                    "8) Results: stats / findings / export / diff", "9) Save / load profile", "0) Exit"])
            c = self.ask("Select")
            if c == "0":
                self.out("bye."); return
            fn = actions.get(c)
            fn() if fn else self.out("  ! choose 0-9")

    def status_line(self):
        on = [k for k, _ in TOGGLES if getattr(self.o, k)]
        self.out(f"\n[targets: {len(self.o.urls)} | depth: {self.o.depth} {self.o.strategy} | scope: {self.o.field_scope} | "
                 f"features: {','.join(on) or 'none'} | results: {len(self.results)}]")

    # ------------------------------------------------------------------ 1 targets
    def targets(self):
        self.out(f"  current: {', '.join(self.o.urls) or '(none)'}")
        v = self.ask("URL(s) comma-separated, or path to a file (blank = keep)")
        if not v:
            return
        if os.path.isfile(v):
            urls = [l.strip() for l in open(v, encoding="utf-8") if l.strip() and not l.startswith("#")]
        else:
            urls = self.csv(v)
        self.o.urls = urls
        self.authorised = False
        self.out(f"  {len(urls)} target(s) set")

    # ------------------------------------------------------------------ 2 presets
    def presets(self):
        names = list(PRESETS)
        self.show("PRESETS", [f"{i}) {n:<9} {PRESETS[n][0]}" for i, n in enumerate(names, 1)] + ["0) back"])
        c = self.ask("Select")
        if c.isdigit() and 1 <= int(c) <= len(names):
            n = names[int(c) - 1]
            apply(self.o, n)
            self.out(f"  preset '{n}' applied")

    # ------------------------------------------------------------------ 3 scope & depth
    def scope(self):
        while True:
            o = self.o
            self.show("SCOPE & DEPTH", [
                f"1) Depth: {o.depth}", f"2) Strategy: {o.strategy}", f"3) Field scope: {o.field_scope}  (rdn/dn/fqdn/regex)",
                f"4) In-scope regex: {o.in_scope or '-'}", f"5) Out-of-scope regex: {o.out_scope or '-'}",
                f"6) No-scope (crawl anything): {'ON' if o.no_scope else 'off'}",
                f"7) Display out-of-scope URLs: {'ON' if o.display_out_scope else 'off'}", "0) back"])
            c = self.ask("Select")
            if c == "0": return
            elif c == "1": o.depth = self.ask_int("Depth", o.depth, 0, 20)
            elif c == "2": o.strategy = "breadth-first" if o.strategy == "depth-first" else "depth-first"
            elif c == "3": o.field_scope = self.ask("rdn | dn | fqdn | regex", o.field_scope)
            elif c == "4": o.in_scope = self.csv(self.ask("regex list, comma-separated (blank clears)"))
            elif c == "5": o.out_scope = self.csv(self.ask("regex list, comma-separated (blank clears)"))
            elif c == "6": o.no_scope = not o.no_scope
            elif c == "7": o.display_out_scope = not o.display_out_scope
            else: self.out("  ! invalid")

    # ------------------------------------------------------------------ 4 features
    def features(self):
        while True:
            self.show("FEATURES (type a number to toggle)",
                      [f"{i}) [{'x' if getattr(self.o, k) else ' '}] {label}" for i, (k, label) in enumerate(TOGGLES, 1)] + ["0) back"])
            c = self.ask("Select")
            if c == "0": return
            if c.isdigit() and 1 <= int(c) <= len(TOGGLES):
                k = TOGGLES[int(c) - 1][0]
                setattr(self.o, k, not getattr(self.o, k))
            else:
                self.out("  ! invalid")

    # ------------------------------------------------------------------ 5 filters
    def filters(self):
        while True:
            o = self.o
            self.show("FILTERS & LIMITS", [
                f"1) Match extensions: {o.ext_match or '-'}", f"2) Filter extensions: {o.ext_filter or '-'}",
                f"3) Match regex: {o.match_regex or '-'}", f"4) Filter regex: {o.filter_regex or '-'}",
                f"5) Match status codes: {o.match_status or '-'}", f"6) Filter status codes: {o.filter_status or '-'}",
                f"7) Ignore query-param values: {'ON' if o.ignore_query_params else 'off'}",
                f"8) Crawl duration (s, 0=unlimited): {o.crawl_duration:g}", f"9) Max pages per domain (0=unlimited): {o.max_domain_pages}",
                "0) back"])
            c = self.ask("Select")
            if c == "0": return
            elif c == "1": o.ext_match = self.csv(self.ask("e.g. php,json,js,none (blank clears)"))
            elif c == "2": o.ext_filter = self.csv(self.ask("e.g. png,css (blank clears)"))
            elif c == "3": o.match_regex = self.csv(self.ask("regex list (blank clears)"))
            elif c == "4": o.filter_regex = self.csv(self.ask("regex list (blank clears)"))
            elif c in ("5", "6"):
                vals = []
                for x in self.csv(self.ask("codes e.g. 200,301 (blank clears)")):
                    if x.isdigit(): vals.append(int(x))
                setattr(o, "match_status" if c == "5" else "filter_status", vals)
            elif c == "7": o.ignore_query_params = not o.ignore_query_params
            elif c == "8": o.crawl_duration = float(self.ask_int("Seconds", int(o.crawl_duration), 0))
            elif c == "9": o.max_domain_pages = self.ask_int("Max pages", o.max_domain_pages, 0)
            else: self.out("  ! invalid")

    # ------------------------------------------------------------------ 6 network
    def network(self):
        while True:
            o = self.o
            self.show("NETWORK", [
                f"1) Concurrency: {o.concurrency}", f"2) Rate limit /s (0=off): {o.rate_limit}",
                f"3) Per-host rate limit /s (0=off): {o.host_rate_limit}", f"4) Delay between requests (s): {o.delay}",
                f"5) Timeout (s): {o.timeout}", f"6) Retries: {o.retries}", f"7) Proxy: {o.proxy or '-'}",
                f"8) Add header ({len(o.headers)} set)", f"9) Verify TLS: {'ON' if o.verify_tls else 'off'}",
                f"10) Disable redirects: {'ON' if o.disable_redirects else 'off'}", "0) back"])
            c = self.ask("Select")
            if c == "0": return
            elif c == "1": o.concurrency = self.ask_int("Workers", o.concurrency, 1, 200)
            elif c == "2": o.rate_limit = self.ask_int("Requests/second", o.rate_limit, 0, 10000)
            elif c == "3": o.host_rate_limit = self.ask_int("Requests/second/host", o.host_rate_limit, 0, 10000)
            elif c == "4":
                try: o.delay = max(0.0, float(self.ask("Seconds", str(o.delay))))
                except ValueError: self.out("  ! not a number")
            elif c == "5": o.timeout = self.ask_int("Seconds", o.timeout, 1, 300)
            elif c == "6": o.retries = self.ask_int("Retries", o.retries, 0, 10)
            elif c == "7": o.proxy = self.ask("http(s)://host:port (blank clears)")
            elif c == "8":
                h = self.ask("Header as 'Name: value'")
                if ":" in h: o.headers.append(h)
                else: self.out("  ! need 'Name: value'")
            elif c == "9": o.verify_tls = not o.verify_tls
            elif c == "10": o.disable_redirects = not o.disable_redirects
            else: self.out("  ! invalid")

    # ------------------------------------------------------------------ 7 start
    def start(self):
        if not self.o.urls:
            self.out("  ! set a target first (option 1)"); return
        if not self.authorised:
            self.out("  Targets: " + ", ".join(self.o.urls))
            if self.ask("Do you own these or have written permission to test them? (yes/no)", "no").lower() not in ("y", "yes"):
                self.out("  aborted."); return
            self.authorised = True
        o = dataclasses.replace(self.o, jsonl=False, silent=True)
        shown = []

        def emit(rec):
            shown.append(1)
            self.out(f"  [{rec['response']['status_code']}] {rec['request']['endpoint']}")

        c = Crawler(o, emit=emit)
        done = threading.Event()

        def progress():
            while not done.wait(3):
                self.out(f"  … fetched {c.fetched}, queued {len(c.frontier)}")

        threading.Thread(target=progress, daemon=True).start()
        t0 = time.time()
        try:
            self.results = c.run()
        finally:
            done.set()
        self.out(f"\n  done: {len(self.results)} endpoints in {time.time() - t0:.1f}s ({c.fetched} requests). Use option 8 to analyse/export.")

    # ------------------------------------------------------------------ 8 results
    def results_menu(self):
        if not self.results:
            self.out("  ! no results yet — run a crawl (7) or load a file"); 
            f = self.ask("Load results from .jsonl (blank = back)")
            if f and os.path.isfile(f): self.results = analysis.load_jsonl(f)
            else: return
        while True:
            self.show("RESULTS", ["1) Summary / stats", "2) List / search", "3) Parameters found", "4) Findings (secrets, forms, API, 401/403, 5xx...)",
                                  "5) Export (txt / jsonl / csv / html report)", "6) Diff against an earlier scan file", "0) back"])
            c = self.ask("Select")
            if c == "0": return
            elif c == "1":
                for k, v in analysis.summarize(self.results).items():
                    self.out(f"  {k}: {v}")
            elif c == "2":
                q, st = self.ask("Contains text (blank = all)").lower(), self.ask("Status code (blank = any)")
                hits = [r for r in self.results if q in r["request"]["endpoint"].lower()
                        and (not st or str(r["response"].get("status_code")) == st)]
                for r in hits[:200]:
                    self.out(f"  [{r['response'].get('status_code')}] {r['request']['endpoint']}")
                self.out(f"  {len(hits)} match(es)" + (" (first 200 shown)" if len(hits) > 200 else ""))
            elif c == "3":
                for k, n in list(analysis.parameters(self.results).items())[:100]:
                    self.out(f"  {k}  x{n}")
            elif c == "4":
                f = analysis.findings(self.results)
                for k, v in f.items():
                    self.out(f"\n  {k} ({len(v)})")
                    for x in v[:25]: self.out(f"    {x}")
                if not f: self.out("  nothing notable")
            elif c == "5": self.export()
            elif c == "6":
                p = self.ask("Earlier .jsonl (or plain URL list) file")
                if os.path.isfile(p):
                    new, gone = analysis.diff(analysis.load_jsonl(p), self.results)
                    self.out(f"  NEW ({len(new)}):"); [self.out("   + " + u) for u in new[:100]]
                    self.out(f"  GONE ({len(gone)}):"); [self.out("   - " + u) for u in gone[:100]]
                else: self.out("  ! file not found")
            else: self.out("  ! invalid")

    def export(self):
        self.show("EXPORT", ["1) txt (urls)", "2) jsonl", "3) csv", "4) html report", "0) back"])
        c = self.ask("Select")
        fmt = {"1": ("txt", analysis.to_txt), "2": ("jsonl", analysis.to_jsonl), "3": ("csv", analysis.to_csv),
               "4": ("html", analysis.to_html)}.get(c)
        if not fmt: return
        path = self.ask("File name", f"crawlforge-results.{fmt[0]}")
        try:
            fmt[1](self.results, path); self.out(f"  wrote {os.path.abspath(path)}")
        except OSError as e:
            self.out(f"  ! {e}")

    # ------------------------------------------------------------------ 9 profiles
    def profiles(self):
        self.show("PROFILES", ["1) Save current settings", "2) Load settings", "3) Show settings", "0) back"])
        c = self.ask("Select")
        if c == "1":
            p = self.ask("File", "crawlforge-profile.json")
            with open(p, "w", encoding="utf-8") as fh: json.dump(dataclasses.asdict(self.o), fh, indent=2)
            self.out(f"  saved {p}")
        elif c == "2":
            p = self.ask("File", "crawlforge-profile.json")
            try:
                d = json.load(open(p, encoding="utf-8"))
                self.o = Options(**{k: v for k, v in d.items() if k in {f.name for f in dataclasses.fields(Options)}})
                self.authorised = False
                self.out("  loaded")
            except (OSError, ValueError, TypeError) as e:
                self.out(f"  ! {e}")
        elif c == "3":
            for k, v in dataclasses.asdict(self.o).items(): self.out(f"  {k}: {v}")


def run_menu(opts: Options | None = None) -> int:
    try:
        Menu(opts).run()
    except (KeyboardInterrupt, SystemExit):
        print("\nbye.")
    return 0
