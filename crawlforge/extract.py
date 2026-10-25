"""Extraction helpers: HTML links/forms, JS endpoints, robots/sitemap, secrets, tech detection."""
from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin

URL_ATTRS = {
    ("a", "href"), ("area", "href"), ("link", "href"), ("script", "src"), ("img", "src"),
    ("iframe", "src"), ("frame", "src"), ("embed", "src"), ("source", "src"), ("video", "src"),
    ("audio", "src"), ("track", "src"), ("object", "data"), ("form", "action"),
    ("button", "formaction"), ("input", "formaction"), ("blockquote", "cite"),
}
GENERIC_DATA_ATTRS = ("data-src", "data-href", "data-url")


class PageParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base = base_url
        self.links: list[tuple[str, str, str]] = []  # (url, tag, attr)
        self.forms: list[dict] = []
        self.inline_js: list[str] = []
        self.title = ""
        self._in_title = False
        self._in_script = False
        self._script_has_src = False
        self._form: dict | None = None
        self._buf: list[str] = []

    def _add(self, raw, tag, attr):
        raw = (raw or "").strip()
        if not raw or raw.startswith(("javascript:", "mailto:", "tel:", "data:", "#")):
            return
        self.links.append((urljoin(self.base, raw), tag, attr))

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "base" and a.get("href"):
            self.base = urljoin(self.base, a["href"])
            return
        if tag == "title":
            self._in_title = True
        if tag == "script":
            self._in_script = True
            self._script_has_src = "src" in a
            self._buf = []
        if tag == "meta" and a.get("http-equiv", "").lower() == "refresh":
            m = re.search(r"url\s*=\s*['\"]?([^'\";]+)", a.get("content", ""), re.I)
            if m:
                self._add(m.group(1), "meta", "content")
        for (t, attr) in URL_ATTRS:
            if t == tag and attr in a:
                self._add(a[attr], tag, attr)
        if tag == "input" and a.get("type", "").lower() == "image" and "src" in a:
            self._add(a["src"], tag, "src")
        for attr in GENERIC_DATA_ATTRS:
            if attr in a:
                self._add(a[attr], tag, attr)
        for attr in ("srcset", "data-srcset"):
            if attr in a:
                for part in a[attr].split(","):
                    bits = part.strip().split()
                    if bits:
                        self._add(bits[0], tag, attr)
        if tag == "form":
            self._form = {
                "method": (a.get("method") or "GET").upper(),
                "action": urljoin(self.base, a.get("action", "")) if a.get("action", "") else self.base,
                "enctype": a.get("enctype", ""),
                "parameters": [],
                "fields": [],
            }
        elif tag in ("input", "textarea", "select", "button") and self._form is not None:
            name = a.get("name")
            if name:
                self._form["parameters"].append(name)
                self._form["fields"].append(
                    {"tag": tag, "name": name, "type": a.get("type", "text" if tag == "input" else tag),
                     "value": a.get("value", "")})

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "script":
            self._in_script = False
            if not self._script_has_src and self._buf:
                self.inline_js.append("".join(self._buf))
            self._buf = []
        elif tag == "form" and self._form is not None:
            self.forms.append(self._form)
            self._form = None

    def handle_data(self, data):
        if self._in_title and len(self.title) < 300:
            self.title += data
        if self._in_script:
            self._buf.append(data)


def parse_html(body: str, base_url: str) -> PageParser:
    p = PageParser(base_url)
    try:
        p.feed(body)
        p.close()
    except Exception:  # malformed HTML must never kill a worker
        pass
    p.title = " ".join(p.title.split())
    return p


# --------------------------------------------------------------------------- JS endpoints
_JS_STRING = re.compile(
    r"""["'`]((?:https?:)?//[^\s"'`<>\\]{4,}|/(?!/)[A-Za-z0-9_\-./~%?=&#:@+,\[\]{}]{1,}|\.{1,2}/[A-Za-z0-9_\-./]+)["'`]"""
)
_JS_CALL = re.compile(
    r"""(?:fetch|axios(?:\.\w+)?|\$\.(?:get|post|ajax|getJSON)|\.open|XMLHttpRequest)\s*\(\s*(?:["'][A-Z]+["']\s*,\s*)?["'`]([^"'`\s]+)["'`]"""
)
_JUNK = re.compile(r"^/+$|^\.{1,2}/?$|\.(?:woff2?|ttf|eot)$|^/[*+?]|\{\{|\$\{")


def js_endpoints(src: str, base_url: str) -> list[str]:
    found: dict[str, None] = {}
    for rx in (_JS_STRING, _JS_CALL):
        for m in rx.finditer(src):
            raw = m.group(1)
            if len(raw) < 2 or _JUNK.search(raw):
                continue
            if raw.startswith("/") and "." not in raw.rsplit("/", 1)[-1] and raw.count("/") < 2 and "?" not in raw:
                # single-segment bare words like "/n" are mostly regex/format noise
                if len(raw) < 4:
                    continue
            try:
                found[urljoin(base_url, raw)] = None
            except ValueError:
                continue
    return list(found)


# --------------------------------------------------------------------------- robots / sitemap
def parse_robots(text: str, base_url: str) -> tuple[list[str], list[str]]:
    paths, sitemaps = [], []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip().lower(), val.strip()
        if key in ("allow", "disallow") and val and val not in ("/", "*"):
            paths.append(urljoin(base_url, val.replace("*", "").rstrip("$")))
        elif key == "sitemap" and val:
            sitemaps.append(val)
    return paths, sitemaps


def parse_sitemap(text: str) -> list[str]:
    return [u.strip() for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", text, re.I)]


# --------------------------------------------------------------------------- secrets
SECRET_PATTERNS = {
    "aws-access-key-id": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "google-api-key": re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    "slack-token": re.compile(r"\bxox[abprs]-[0-9A-Za-z\-]{10,48}\b"),
    "github-token": re.compile(r"\bgh[pousr]_[0-9A-Za-z]{36,}\b"),
    "stripe-live-key": re.compile(r"\b[sr]k_live_[0-9a-zA-Z]{20,}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"),
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    "generic-secret-assignment": re.compile(
        r"""(?i)\b(?:api[_-]?key|secret|access[_-]?token|auth[_-]?token|passwd|password)\b["']?\s*[:=]\s*["']([A-Za-z0-9_\-/+=]{12,})["']"""),
}


def find_secrets(text: str) -> list[dict]:
    out = []
    for name, rx in SECRET_PATTERNS.items():
        for m in rx.finditer(text):
            val = m.group(0)
            masked = val[:6] + "…" + val[-2:] if len(val) > 12 else "***"
            out.append({"type": name, "match": masked})
    return out


# --------------------------------------------------------------------------- tech detection
TECH_SIGNATURES = [
    ("WordPress", "body", re.compile(r"wp-content|wp-includes", re.I)),
    ("jQuery", "body", re.compile(r"jquery[.\-/][\d.]*(?:min\.)?js", re.I)),
    ("React", "body", re.compile(r"data-reactroot|__REACT_DEVTOOLS|react(?:\.production|-dom)", re.I)),
    ("Vue.js", "body", re.compile(r"vue(?:\.runtime)?(?:\.min)?\.js|data-v-[0-9a-f]{6,}", re.I)),
    ("Angular", "body", re.compile(r"ng-version=|ng-app", re.I)),
    ("Next.js", "body", re.compile(r"/_next/static|__NEXT_DATA__")),
    ("Bootstrap", "body", re.compile(r"bootstrap(?:\.min)?\.(?:css|js)", re.I)),
    ("nginx", "server", re.compile(r"nginx", re.I)),
    ("Apache", "server", re.compile(r"apache", re.I)),
    ("Cloudflare", "server", re.compile(r"cloudflare", re.I)),
    ("PHP", "x-powered-by", re.compile(r"php", re.I)),
    ("ASP.NET", "x-powered-by", re.compile(r"asp\.net", re.I)),
    ("Express", "x-powered-by", re.compile(r"express", re.I)),
]


def detect_tech(headers: dict, body: str) -> list[str]:
    hl = {k.lower(): v for k, v in headers.items()}
    techs = []
    for name, where, rx in TECH_SIGNATURES:
        hay = body[:200_000] if where == "body" else hl.get(where, "")
        if hay and rx.search(hay):
            techs.append(name)
    return techs
