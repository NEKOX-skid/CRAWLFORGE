"""URL normalisation, extension filters, similar-URL detection and content similarity."""
from __future__ import annotations

import hashlib
import re
import threading
from urllib.parse import parse_qsl, urlsplit, urlunsplit

DEFAULT_EXT_FILTER = {
    "png", "apng", "bmp", "gif", "ico", "cur", "jpg", "jpeg", "jfif", "pjp", "pjpeg", "svg", "tif", "tiff",
    "webp", "avif", "css", "scss", "wof", "wof2", "woff", "woff2", "ttf", "otf", "eot", "mp3", "mp4",
    "webm", "ogg", "wav", "avi", "mov", "zip", "gz", "tar", "rar", "7z",
}


def normalize(url: str) -> str:
    p = urlsplit(url.strip())
    scheme, host = p.scheme.lower(), (p.hostname or "").lower()
    if not scheme or not host:
        return ""
    port = p.port
    netloc = host if port in (None, 80, 443) and not (port == 80 and scheme == "https") else f"{host}:{port}"
    if ":" in host:
        netloc = f"[{host}]" + (f":{port}" if port else "")
    path = p.path or "/"
    return urlunsplit((scheme, netloc, path, p.query, ""))


def extension(url: str) -> str:
    last = urlsplit(url).path.rsplit("/", 1)[-1]
    return last.rsplit(".", 1)[-1].lower() if "." in last else ""


def dedup_key(method: str, url: str, ignore_query_values: bool) -> str:
    if not ignore_query_values:
        return f"{method} {url}"
    p = urlsplit(url)
    names = ",".join(sorted({k for k, _ in parse_qsl(p.query, keep_blank_values=True)}))
    return f"{method} {p.scheme}://{p.netloc}{p.path}?{names}"


class SimilarURLFilter:
    """Skips URLs like /users/123, /users/456 ... once a path slot has too many distinct values."""

    def __init__(self, threshold: int = 10):
        self.threshold = threshold
        self.slots: dict[tuple, set] = {}
        self.lock = threading.Lock()

    def allow(self, url: str) -> bool:
        p = urlsplit(url)
        segs = [s for s in p.path.split("/") if s]
        if not segs:
            return True
        with self.lock:
            blocked = False
            keys = []
            for i, seg in enumerate(segs):
                key = (p.netloc, len(segs), tuple(segs[:i]), tuple(segs[i + 1:]))
                keys.append((key, seg))
                values = self.slots.get(key, set())
                if seg not in values and len(values) >= self.threshold:
                    blocked = True
            if blocked:
                return False
            for key, seg in keys:
                self.slots.setdefault(key, set()).add(seg)
            return True


def simhash(text: str, bits: int = 64) -> int:
    weights = [0] * bits
    for tok in re.findall(r"[A-Za-z0-9]{3,}", text.lower())[:5000]:
        h = int.from_bytes(hashlib.md5(tok.encode()).digest()[:8], "big")
        for i in range(bits):
            weights[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i, w in enumerate(weights):
        if w > 0:
            out |= 1 << i
    return out


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


class ContentDeduper:
    """Exact (sha1) dedup, with optional simhash near-duplicate clustering."""

    def __init__(self, similar: bool = False, distance: int = 3, budget: int = 1):
        self.exact: set[str] = set()
        self.clusters: list[list] = []  # [simhash, seen_count]
        self.similar, self.distance, self.budget = similar, distance, budget
        self.lock = threading.Lock()

    def is_duplicate(self, body: str) -> bool:
        digest = hashlib.sha1(body.encode("utf-8", "ignore")).hexdigest()
        with self.lock:
            if digest in self.exact:
                return True
            self.exact.add(digest)
            if not self.similar:
                return False
            sh = simhash(body)
            for c in self.clusters:
                if hamming(sh, c[0]) <= self.distance:
                    c[1] += 1
                    return c[1] > self.budget
            self.clusters.append([sh, 1])
            return False
