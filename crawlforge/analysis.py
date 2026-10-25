"""Post-crawl analysis and export: stats, params, findings, diff, csv/html/txt reports."""
from __future__ import annotations

import csv
import html
import json
from collections import Counter
from urllib.parse import parse_qsl, urlsplit

from .filters import extension


def load_jsonl(path: str) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("{"):
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
            elif line.startswith("http"):  # plain url list also accepted for diffs
                out.append({"request": {"endpoint": line}, "response": {}})
    return out


def _ep(r): return r["request"]["endpoint"]


def summarize(results: list[dict]) -> dict:
    status = Counter(str(r["response"].get("status_code", "?")) for r in results)
    ctype = Counter(r["response"].get("content_type") or "unknown" for r in results)
    hosts = Counter(urlsplit(_ep(r)).netloc for r in results)
    exts = Counter(extension(_ep(r)) or "none" for r in results)
    depth = Counter(str(r["request"].get("depth", "?")) for r in results)
    return {"total": len(results), "status": dict(status.most_common()), "content_types": dict(ctype.most_common(8)),
            "hosts": dict(hosts.most_common(10)), "extensions": dict(exts.most_common(10)), "depth": dict(sorted(depth.items()))}


def parameters(results: list[dict]) -> dict[str, int]:
    c: Counter = Counter()
    for r in results:
        for k, _ in parse_qsl(urlsplit(_ep(r)).query, keep_blank_values=True):
            c[k] += 1
        for f in r["response"].get("forms", []):
            for p in f.get("parameters", []):
                c[p] += 1
    return dict(c.most_common())


def findings(results: list[dict]) -> dict[str, list[str]]:
    f: dict[str, list[str]] = {"secrets": [], "forms": [], "api-like": [], "auth (401/403)": [], "server errors (5xx)": [],
                               "with parameters": [], "interesting files": []}
    interesting = (".env", ".git", ".bak", ".sql", ".old", ".zip", "backup", "config", "admin", "phpinfo", ".log", "swagger", "graphql")
    for r in results:
        u, resp = _ep(r), r["response"]
        for s in resp.get("secrets", []):
            f["secrets"].append(f'{u}  [{s["type"]}] {s["match"]}')
        if resp.get("forms"):
            f["forms"].append(f'{u}  ({len(resp["forms"])} form(s))')
        low = u.lower()
        if "/api/" in low or "/v1/" in low or "/v2/" in low or "graphql" in low or "json" in (resp.get("content_type") or ""):
            f["api-like"].append(u)
        code = resp.get("status_code", 0)
        if code in (401, 403): f["auth (401/403)"].append(f"{u}  [{code}]")
        if 500 <= code < 600: f["server errors (5xx)"].append(f"{u}  [{code}]")
        if urlsplit(u).query: f["with parameters"].append(u)
        if any(t in low for t in interesting): f["interesting files"].append(u)
    return {k: v for k, v in f.items() if v}


def diff(old: list[dict], new: list[dict]) -> tuple[list[str], list[str]]:
    a, b = {_ep(r) for r in old}, {_ep(r) for r in new}
    return sorted(b - a), sorted(a - b)


def to_txt(results, path):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_ep(r) for r in results) + "\n")


def to_jsonl(results, path):
    with open(path, "w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def to_csv(results, path):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["url", "method", "status", "content_type", "length", "title", "depth", "found_on", "technologies"])
        for r in results:
            q, p = r["request"], r["response"]
            cell = lambda v: "'" + v if isinstance(v, str) and v[:1] in "=+-@" else v  # neutralise CSV formula injection
            w.writerow([cell(q["endpoint"]), q.get("method"), p.get("status_code"), p.get("content_type"),
                        p.get("content_length"), cell(p.get("title", "")), q.get("depth"), cell(q.get("source", "")),
                        ";".join(p.get("technologies", []))])


def to_html(results, path, title="Crawlforge report"):
    s, e = summarize(results), html.escape
    def table(d): return "".join(f"<tr><td>{e(str(k))}</td><td>{v}</td></tr>" for k, v in d.items())
    rows = "".join(
        f'<tr><td>{r["response"].get("status_code","")}</td><td><a href="{e(_ep(r), quote=True)}" rel="noreferrer">{e(_ep(r))}</a></td>'
        f'<td>{e(r["response"].get("title",""))}</td><td>{e(r["response"].get("content_type",""))}</td></tr>' for r in results)
    fnd = "".join(f"<h3>{e(k)} ({len(v)})</h3><ul>{''.join('<li>'+e(x)+'</li>' for x in v[:200])}</ul>" for k, v in findings(results).items())
    doc = f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><style>
:root{{--bg:#fff;--fg:#1a1a1a;--mut:#666;--line:#ddd}}
@media(prefers-color-scheme:dark){{:root{{--bg:#16181d;--fg:#e8e8e8;--mut:#9aa;--line:#333}}}}
body{{font:14px system-ui,sans-serif;background:var(--bg);color:var(--fg);margin:2rem auto;max-width:1100px;padding:0 1rem}}
table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid var(--line);padding:4px 8px;text-align:left;word-break:break-all}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1rem}}a{{color:inherit}}h1,h2,h3{{margin:1.2rem 0 .4rem}}
</style><h1>{e(title)}</h1><p>{s["total"]} endpoints</p>
<div class="grid"><div><h3>Status</h3><table>{table(s["status"])}</table></div><div><h3>Hosts</h3><table>{table(s["hosts"])}</table></div>
<div><h3>Extensions</h3><table>{table(s["extensions"])}</table></div></div>
<h2>Findings</h2>{fnd or "<p>None.</p>"}<h2>Endpoints</h2>
<div style="overflow-x:auto"><table><tr><th>Status</th><th>URL</th><th>Title</th><th>Type</th></tr>{rows}</table></div>"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
