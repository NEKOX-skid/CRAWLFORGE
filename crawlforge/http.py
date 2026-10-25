"""HTTP client: retries, proxy, gzip, size cap, optional redirect disabling, rate limiting."""
from __future__ import annotations

import gzip
import ssl
import threading
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass, field

UA = "Mozilla/5.0 (compatible; crawlforge/0.2)"


class RateLimiter:
    """Global + optional per-host spacing limiter (thread safe)."""

    def __init__(self, per_second: int = 0, per_host_second: int = 0, delay: float = 0.0):
        self.gap = 1.0 / per_second if per_second else 0.0
        self.host_gap = 1.0 / per_host_second if per_host_second else 0.0
        self.delay = delay
        self.next_global = 0.0
        self.next_host: dict[str, float] = {}
        self.lock = threading.Lock()

    def wait(self, host: str):
        with self.lock:
            now = time.monotonic()
            start = max(now, self.next_global, self.next_host.get(host, 0.0))
            self.next_global = start + self.gap
            self.next_host[host] = start + max(self.host_gap, self.delay)
        sleep = start - time.monotonic()
        if sleep > 0:
            time.sleep(sleep)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


@dataclass
class Response:
    url: str
    status: int = 0
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    error: str = ""
    final_url: str = ""

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";")[0].strip().lower()

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")


class Client:
    def __init__(self, timeout=10, retries=1, proxy="", headers=None, max_size=4 * 1024 * 1024,
                 follow_redirects=True, verify_tls=False, limiter: RateLimiter | None = None):
        self.timeout, self.retries, self.max_size = timeout, retries, max_size
        self.limiter = limiter or RateLimiter()
        ctx = ssl.create_default_context()
        if not verify_tls:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        handlers = [urllib.request.HTTPSHandler(context=ctx)]
        if proxy:
            handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        if not follow_redirects:
            handlers.append(_NoRedirect())
        self.opener = urllib.request.build_opener(*handlers)
        self.headers = {"User-Agent": UA, "Accept": "*/*", "Accept-Encoding": "gzip, deflate"}
        for h in headers or []:
            if ":" in h:
                k, _, v = h.partition(":")
                self.headers[k.strip()] = v.strip()

    def _read(self, resp) -> bytes:
        raw = resp.read(self.max_size)
        enc = (resp.headers.get("Content-Encoding") or "").lower()
        try:
            if enc == "gzip":
                raw = gzip.decompress(raw)
            elif enc == "deflate":
                raw = zlib.decompress(raw)
        except Exception:
            pass
        return raw

    def request(self, url: str, method: str = "GET", data: bytes | None = None) -> Response:
        from urllib.parse import urlsplit
        host = urlsplit(url).netloc
        last_err = ""
        for attempt in range(self.retries + 1):
            self.limiter.wait(host)
            req = urllib.request.Request(url, data=data, method=method, headers=self.headers)
            if data is not None:
                req.add_header("Content-Type", "application/x-www-form-urlencoded")
            try:
                with self.opener.open(req, timeout=self.timeout) as r:
                    return Response(url, r.status, {k.lower(): v for k, v in r.headers.items()},
                                    self._read(r), final_url=r.geturl())
            except urllib.error.HTTPError as e:  # 3xx (when redirects off), 4xx, 5xx still carry data
                try:
                    body = self._read(e)
                except Exception:
                    body = b""
                return Response(url, e.code, {k.lower(): v for k, v in e.headers.items()}, body, final_url=url)
            except Exception as e:  # network / TLS / timeout -> retry
                last_err = f"{type(e).__name__}: {e}"
                time.sleep(min(0.25 * (attempt + 1), 1.0))
        return Response(url, 0, error=last_err)
