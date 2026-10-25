"""Scope management: rdn / dn / fqdn / custom regex, plus in/out-of-scope regex lists."""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

_TWO_LEVEL = {"co", "com", "org", "net", "gov", "edu", "ac", "or", "ne", "go"}


def hostname(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def rdn(host: str) -> str:
    """Root domain name (naive public-suffix handling, good enough without external data)."""
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    if len(parts[-1]) == 2 and parts[-2] in _TWO_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def dn(host: str) -> str:
    """Domain name keyword = RDN without its TLD (example.com -> example)."""
    return rdn(host).split(".")[0]


class Scope:
    def __init__(self, seeds, field_scope="rdn", in_scope=None, out_scope=None, no_scope=False):
        self.no_scope = no_scope
        self.field = field_scope
        self.in_rx = [re.compile(p) for p in (in_scope or [])]
        self.out_rx = [re.compile(p) for p in (out_scope or [])]
        self.seed_hosts = {hostname(s) for s in seeds}
        self.custom = None
        if field_scope not in ("rdn", "dn", "fqdn"):
            self.custom = re.compile(field_scope)

    def _host_ok(self, host: str) -> bool:
        if self.custom:
            return bool(self.custom.search(host))
        for sh in self.seed_hosts:
            if self.field == "fqdn" and host == sh:
                return True
            if self.field == "rdn" and rdn(host) == rdn(sh):
                return True
            if self.field == "dn" and dn(host) == dn(sh):
                return True
        return False

    def allowed(self, url: str) -> bool:
        if any(r.search(url) for r in self.out_rx):
            return False
        if self.in_rx:  # explicit in-scope regexes override host scope (katana semantics)
            return any(r.search(url) for r in self.in_rx)
        if self.no_scope:
            return True
        return self._host_ok(hostname(url))
