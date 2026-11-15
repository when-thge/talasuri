"""Coordinate parsing, formatting and validation: the only implementation on the backend.

``frontend/src/coords.ts`` is its line-for-line twin. Both run the same cases from
``shared/coords_cases.json`` in their test suites, so the browser and the API accept and
print exactly the same things.
"""
from __future__ import annotations

import re

_N = r"(\d+(?:\.\d*)?|\.\d+)"
_NUM = re.compile(rf"[+-]?{_N}")
_COLONS = re.compile(rf"([+-]?){_N}(?::{_N}(?::{_N})?)?")                     # 08:55:10.8
_UNITS = re.compile(rf"([+-]?){_N}([hd])(?:{_N}[m']?(?:{_N}[s\"]?)?)?")       # 08h55m10.8s
_LETTERS = re.compile(r"[a-ce-gi-ln-rt-zA-Z]")       # any letter other than d, h, m, s


class CoordinateError(ValueError):
    """The text is a coordinate pair, but an impossible one."""


def check_range(ra: float, dec: float) -> tuple[float, float]:
    if not (0 <= ra < 360) or not (-90 <= dec <= 90):
        raise CoordinateError(f"coordinates out of range: RA={ra}, Dec={dec}")
    return ra, dec


def _sexagesimal_degrees(token: str, hours: bool) -> float | None:
    """'-07:14:42.53', '08h55m10.8s', '12d30m' -> degrees. ``hours`` says whether a value
    with no unit letter is in hours (RA) or degrees (Dec); an explicit h or d wins. None
    if the token is not one to three numbers, or minutes/seconds exceed 60."""
    m = _UNITS.fullmatch(token)
    if m:
        sign, first, unit, *rest = m.groups()
        hours = unit == "h"
    else:
        m = _COLONS.fullmatch(token)
        if not m:
            return None
        sign, first, *rest = m.groups()
    vals = [float(first)] + [float(v) for v in rest if v is not None]
    if any(v > 60 for v in vals[1:]):
        return None
    value = sum(v / 60 ** i for i, v in enumerate(vals))
    return (-value if sign == "-" else value) * (15.0 if hours else 1.0)


def parse_coordinates(text: str) -> tuple[float, float] | None:
    """Parse "RA Dec" in decimal degrees or sexagesimal. Returns None if ``text`` does
    not look like coordinates (so the caller can try name resolution).

    Accepts e.g. ``133.79513 -7.24515``, ``133.79513,-7.24515``,
    ``08:55:10.831 -07:14:42.53``, ``08h55m10.831s -07d14m42.53s``,
    ``08 55 10.831 -07 14 42.53`` and Unicode minus/prime symbols. Two plain numbers are
    degrees; anything sexagesimal reads RA in hours.
    """
    s = text.strip()
    s = (s.replace("−", "-").replace("–", "-").replace("′", "'")
         .replace("″", '"').replace("°", "d"))
    if not s or _LETTERS.search(s.replace("deg", "")):
        return None  # contains letters other than h/m/s/d -> probably a name
    tokens = s.replace(",", " ").replace("deg", " ").split()
    if len(tokens) == 2 and all(_NUM.fullmatch(t) for t in tokens):
        ra, dec = float(tokens[0]), float(tokens[1])
    else:
        if len(tokens) == 6:
            tokens = [":".join(tokens[:3]), ":".join(tokens[3:])]
        if len(tokens) != 2:
            return None
        ra, dec = _sexagesimal_degrees(tokens[0], True), _sexagesimal_degrees(tokens[1], False)
        if ra is None or dec is None:
            return None
    return check_range(ra, dec)


def _sexagesimal_text(value: float, precision: int, modulo: int = 0) -> str:
    """Non-negative ``value`` (hours or degrees) as ``HH:MM:SS.ss``; rounding carries, and
    with ``modulo`` (24 for RA) a value that rounds up to it wraps to zero."""
    scale = 10 ** precision
    total = int(value * 3600 * scale + 0.5)
    if modulo:
        total %= modulo * 3600 * scale
    whole, frac = divmod(total, scale)
    h, rem = divmod(whole, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" + (f".{frac:0{precision}d}" if precision else "")


def format_sexagesimal(ra: float, dec: float, ra_precision: int = 2, dec_precision: int = 2) -> str:
    """``17:57:48.50 +04:41:36.21`` (RA in hours, Dec in degrees)."""
    sign = "-" if dec < 0 else "+"
    return f"{_sexagesimal_text(ra / 15.0, ra_precision, 24)} {sign}{_sexagesimal_text(abs(dec), dec_precision)}"


def _fixed(value: float, precision: int, modulo: int = 0) -> str:
    """Fixed-point text built from integers, so both languages round identically."""
    scale = 10 ** precision
    n = int(abs(value) * scale + 0.5)
    if modulo:
        n %= modulo * scale
    sign = "-" if value < 0 and n > 0 else ""
    return f"{sign}{n // scale}" + (f".{n % scale:0{precision}d}" if precision else "")


def format_decimal(ra: float, dec: float, precision: int = 5) -> str:
    """``133.79513 -7.24515``: decimal degrees, which :func:`parse_coordinates` reads back
    (an RA that rounds up to 360 wraps to 0)."""
    return f"{_fixed(ra, precision, 360)} {_fixed(dec, precision)}"
