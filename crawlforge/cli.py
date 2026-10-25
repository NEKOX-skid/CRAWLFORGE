"""Command line interface (flag names mirror katana where practical)."""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .crawler import Crawler, Options


def _csv(v):
    return [x.strip() for x in v.split(",") if x.strip()] if v else []


def _file_or_csv(v):
    import os
    if v and os.path.isfile(v):
        return [l.strip() for l in open(v, encoding="utf-8") if l.strip()]
    return _csv(v)


def _duration(v: str) -> float:
    if not v:
        return 0.0
    unit = {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(v[-1])
    return float(v[:-1]) * unit if unit else float(v)


def build_parser():
    p = argparse.ArgumentParser(prog="crawlforge", allow_abbrev=False,
                                description="Fast, scope-aware web crawler. Only crawl targets you are authorised to test.")
    a = p.add_argument
    a("-u", "-list", dest="urls", default="", help="target url(s), comma separated or file")
    a("-config", dest="config", default="", help="JSON config file (keys = option names)")
    a("-resume", dest="resume", default="", help="state file: resumes if present, saved on interrupt/limit")
    a("-d", "-depth", dest="depth", type=int, default=3, help="maximum depth to crawl")
    a("-s", "-strategy", dest="strategy", choices=["depth-first", "breadth-first"], default="depth-first")
    a("-jc", "-js-crawl", dest="js_crawl", action="store_true", help="extract endpoints from JavaScript")
    a("-kf", "-known-files", dest="known_files", action="store_true", help="seed from robots.txt / sitemap.xml")
    a("-pc", "-path-climb", dest="path_climb", action="store_true", help="also crawl parent paths")
    a("-fx", "-form-extraction", dest="form_extraction", action="store_true", help="include forms in jsonl")
    a("-aff", "-automatic-form-fill", dest="auto_form_fill", action="store_true", help="fill & follow GET forms")
    a("-td", "-tech-detect", dest="tech_detect", action="store_true")
    a("-secrets", dest="secrets", action="store_true", help="flag likely secrets in responses (masked)")
    a("-ct", "-crawl-duration", dest="crawl_duration", default="0", help="e.g. 30s, 5m, 1h")
    a("-mdp", "-max-domain-pages", dest="max_domain_pages", type=int, default=0)
    a("-iqp", "-ignore-query-params", dest="ignore_query_params", action="store_true")
    a("-fsu", "-filter-similar", dest="filter_similar", action="store_true")
    a("-fst", "-filter-similar-threshold", dest="filter_similar_threshold", type=int, default=10)
    a("-pcs", "-page-content-similar", dest="content_similar", action="store_true", help="simhash near-dup filter")
    a("-pcsd", dest="content_similar_distance", type=int, default=3)
    a("-duf", "-disable-unique-filter", dest="no_dedup", action="store_true")
    a("-dr", "-disable-redirects", dest="disable_redirects", action="store_true")
    a("-H", "-headers", dest="headers", action="append", default=[], help="header 'Name: value' (repeatable)")
    a("-proxy", dest="proxy", default="")
    a("-timeout", dest="timeout", type=int, default=10)
    a("-retry", dest="retries", type=int, default=1)
    a("-mrs", "-max-response-size", dest="max_response_size", type=int, default=4 * 1024 * 1024)
    a("-verify-tls", dest="verify_tls", action="store_true")
    # scope
    a("-cs", "-crawl-scope", dest="in_scope", default="")
    a("-cos", "-crawl-out-scope", dest="out_scope", default="")
    a("-fs", "-field-scope", dest="field_scope", default="rdn", help="rdn | dn | fqdn | custom regex")
    a("-ns", "-no-scope", dest="no_scope", action="store_true")
    a("-do", "-display-out-scope", dest="display_out_scope", action="store_true")
    # filters
    a("-em", "-extension-match", dest="ext_match", default="")
    a("-ef", "-extension-filter", dest="ext_filter", default="")
    a("-ndef", "-no-default-ext-filter", dest="no_default_ext_filter", action="store_true")
    a("-mr", "-match-regex", dest="match_regex", action="append", default=[])
    a("-fr", "-filter-regex", dest="filter_regex", action="append", default=[])
    # rate limit
    a("-c", "-concurrency", dest="concurrency", type=int, default=10)
    a("-rl", "-rate-limit", dest="rate_limit", type=int, default=150)
    a("-hrl", "-host-rate-limit", dest="host_rate_limit", type=int, default=0)
    a("-rd", "-delay", dest="delay", type=float, default=0.0)
    # output
    a("-o", "-output", dest="output", default="")
    a("-j", "-jsonl", dest="jsonl", action="store_true")
    a("-ib", "-include-body", dest="include_body", action="store_true", help="include response body in jsonl")
    a("-sr", "-store-response-dir", dest="store_response_dir", default="")
    a("-silent", dest="silent", action="store_true")
    a("-v", "-verbose", dest="verbose", action="store_true")
    a("-version", dest="version", action="store_true")
    a("-web", dest="web", action="store_true", help="start the local web UI")
    a("-host", dest="host", default="127.0.0.1", help="web UI bind address (default loopback)")
    a("-port", dest="port", type=int, default=8787, help="web UI port")
    a("-no-browser", dest="no_browser", action="store_true")
    a("-menu", dest="menu", action="store_true", help="open the interactive numbered menu")
    a("-preset", dest="preset", choices=["quick", "standard", "deep", "api-hunt", "stealth"], default="")
    a("-mc", "-match-status", dest="match_status", default="", help="only output these status codes (200,301)")
    a("-fc", "-filter-status", dest="filter_status", default="", help="hide these status codes (404,503)")
    a("-report", dest="report", default="", help="write an HTML report after the crawl")
    a("-csv", dest="csv_out", default="", help="write a CSV export after the crawl")
    a("-diff", dest="diff", default="", help="compare against an earlier jsonl/url-list file; print new/gone")
    return p


def to_options(ns) -> Options:
    cfg = {}
    if ns.config:
        with open(ns.config, encoding="utf-8") as fh:
            cfg = json.load(fh)
    o = Options()
    if ns.preset:
        from .presets import apply
        apply(o, ns.preset)
    defaults = vars(build_parser().parse_args([]))
    for k, v in vars(ns).items():
        if hasattr(o, k) and (not ns.preset or v != defaults.get(k)):
            setattr(o, k, v)
    for k, v in cfg.items():  # config file fills only values the CLI left at default
        if hasattr(o, k) and getattr(o, k) in (None, "", 0, False, [], 3, 10, 150):
            setattr(o, k, v)
    o.urls = _file_or_csv(ns.urls)
    o.in_scope, o.out_scope = _file_or_csv(ns.in_scope), _file_or_csv(ns.out_scope)
    o.ext_match, o.ext_filter = _csv(ns.ext_match), _csv(ns.ext_filter)
    o.crawl_duration = _duration(ns.crawl_duration)
    o.content_dedup = not ns.no_dedup
    o.omit_body = not ns.include_body
    o.match_status = [int(x) for x in _csv(ns.match_status) if x.isdigit()]
    o.filter_status = [int(x) for x in _csv(ns.filter_status) if x.isdigit()]
    return o


def main(argv=None) -> int:
    ns = build_parser().parse_args(argv)
    if ns.web:
        from .web import serve
        return serve(ns.host, ns.port, not ns.no_browser)
    if ns.menu or (argv is None and len(sys.argv) == 1 and sys.stdin.isatty()):
        from .menu import run_menu
        return run_menu()
    if ns.version:
        print(f"crawlforge {__version__}")
        return 0
    o = to_options(ns)
    if not o.urls and not sys.stdin.isatty():
        o.urls = [l.strip() for l in sys.stdin if l.strip()]
    if not o.urls:
        print("no target given (use -u or pipe URLs on stdin)", file=sys.stderr)
        return 2
    results = Crawler(o).run()
    from . import analysis
    if ns.csv_out:
        analysis.to_csv(results, ns.csv_out)
    if ns.report:
        analysis.to_html(results, ns.report)
    if ns.diff:
        new, gone = analysis.diff(analysis.load_jsonl(ns.diff), results)
        print(f"[diff] {len(new)} new, {len(gone)} gone", file=sys.stderr)
        for u in new: print(f"+ {u}", file=sys.stderr)
        for u in gone: print(f"- {u}", file=sys.stderr)
    if not o.silent:
        print(f"[inf] {len(results)} endpoints", file=sys.stderr)
    return 0
