"""The one shared HTTP session. Every outbound request (SIA, cutouts, S3 ranges, HiPS
tiles, catalogs, Sesame, SIMBAD, TAP) goes through this client, so connections to IRSA,
S3 and CDS are pooled and reused instead of being re-opened per call."""
from __future__ import annotations

import asyncio

import httpx

from ..config import settings

_state: tuple[asyncio.AbstractEventLoop, httpx.AsyncClient] | None = None
_override: httpx.AsyncClient | None = None    # tests substitute a mock transport here


def client() -> httpx.AsyncClient:
    """The shared client for the running event loop (one per loop: the CLI checks and the
    tests start a fresh loop per target, and a client cannot outlive its loop)."""
    global _state
    if _override is not None:
        return _override
    loop = asyncio.get_running_loop()
    if _state is None or _state[0] is not loop:
        n = settings.s3_concurrency + settings.fetch_concurrency * 2 + 32
        _state = (loop, httpx.AsyncClient(
            follow_redirects=True, timeout=30,
            limits=httpx.Limits(max_connections=n, max_keepalive_connections=n)))
    return _state[1]
