#!/usr/bin/env python3
# wi_util.py — pure, stateless helpers for the worker IT-ops endpoint: version compare, cert
# signature tier, weak-cipher match, cert-expiry days, and config-file parse. No shared state and
# no side effects, so these are unit-tested directly. Co-located module — boot-stack cp's it next
# to worker-itops.py (same as ebg19p.py / knowledge.py / wi_a2a.py).
import re
from datetime import datetime


def vtuple(s):
    """Version string → numeric tuple for correct ordering ('386_510' > '386_59'). None-safe."""
    return tuple(int(x) for x in re.findall(r"\d+", s or ""))


def sig_tier(alg):
    """Certificate signature algorithm → its hash tier (sha512..md2), or None."""
    a = (alg or "").lower()
    for tk in ("sha512", "sha384", "sha256", "sha1", "md5", "md2"):
        if tk in a:
            return tk
    return None


def cipher_bad(x, pats):
    """True if cipher name x matches any weak-cipher pattern (supports the @SHA1MAC family marker)."""
    for p in pats:
        if p == "@SHA1MAC":
            if x.endswith("-SHA"):
                return True
        elif p in x:
            return True
    return False


def days_left(not_after):
    """Days until a YYYY-MM-DD expiry date (negative = expired); None if unparseable."""
    try:
        return (datetime.strptime(not_after, "%Y-%m-%d").date() - datetime.now().date()).days
    except Exception:
        return None


def conf_kv(path):
    """Parse a `key = value` config file → dict (UCI-style; tolerant, uppercase keys ok)."""
    d = {}
    try:
        for line in open(path, encoding="utf-8"):
            m = re.match(r"\s*([A-Za-z0-9_.]+)\s*=\s*(.*?)\s*$", line)
            if m:
                d[m.group(1)] = m.group(2)
    except Exception:
        pass
    return d
