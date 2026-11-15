"""Runtime settings, all overridable via environment variables (prefix SPX_)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(f"SPX_{name}", default)


@dataclass(frozen=True)
class Settings:
    irsa_sia_url: str = _env("IRSA_SIA_URL", "https://irsa.ipac.caltech.edu/SIA")
    irsa_tap_url: str = _env("IRSA_TAP_URL", "https://irsa.ipac.caltech.edu/TAP")
    irsa_base_url: str = _env("IRSA_BASE_URL", "https://irsa.ipac.caltech.edu")
    # Comma-separated, tried in order (CDS, then the CfA mirror).
    sesame_urls: tuple[str, ...] = tuple(_env(
        "SESAME_URLS", "https://cds.unistra.fr/cgi-bin/nph-sesame/-ox/SNV,"
                       "https://vizier.cfa.harvard.edu/viz-bin/nph-sesame/-ox/SNV").split(","))

    # Where cutouts come from: "s3" (byte ranges from the public AWS copy), "ibe" (IRSA's
    # cutout service) or "auto" (S3, falling back to IBE for any image S3 can't serve).
    cutout_source: str = _env("CUTOUT_SOURCE", "auto")
    # SPHEREx all-sky HiPS cube; the app re-serves it one slice at a time (data_access/hips.py).
    spherex_hips_url: str = _env("SPHEREX_HIPS_URL",
                                 "https://irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube")
    s3_base_url: str = _env("S3_BASE_URL", "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com")
    # S3 has no per-client throttling; requests are latency-bound, so run many at once.
    s3_concurrency: int = int(_env("S3_CONCURRENCY", "128"))

    cache_dir: Path = Path(_env("CACHE_DIR", str(Path.home() / ".cache" / "spherex_viewer")))
    # IRSA starts returning 503s at ~16 concurrent cutout requests; 6-8 is a polite, fast setting.
    fetch_concurrency: int = int(_env("FETCH_CONCURRENCY", "8"))
    fetch_timeout_s: float = float(_env("FETCH_TIMEOUT_S", "90"))
    fetch_retries: int = int(_env("FETCH_RETRIES", "5"))
    sia_cache_ttl_s: float = float(_env("SIA_CACHE_TTL_S", str(6 * 3600)))
    # How often the release registry re-queries IRSA for new collections.
    registry_refresh_s: float = float(_env("REGISTRY_REFRESH_S", str(6 * 3600)))
    # Path to optional release overrides (labels, hidden collections, priority).
    releases_file: Path = Path(_env("RELEASES_FILE", str(Path(__file__).with_name("releases.toml"))))

    max_fov_arcmin: float = float(_env("MAX_FOV_ARCMIN", "30"))
    warn_fov_arcmin: float = float(_env("WARN_FOV_ARCMIN", "10"))
    pixel_scale_arcsec: float = 6.15  # native SPHEREx plate scale (s_pixel_scale in ObsCore)
    max_sessions: int = int(_env("MAX_SESSIONS", "8"))

    cors_origins: list[str] = field(default_factory=lambda: _env("CORS_ORIGINS", "*").split(","))
    frontend_dir: Path = Path(_env("FRONTEND_DIR", str(Path(__file__).resolve().parents[2] / "frontend" / "dist")))


settings = Settings()
