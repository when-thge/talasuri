"""The common output grid: north-up, east-left gnomonic (TAN) projection centred on
the target, at the native SPHEREx plate scale."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from astropy.wcs import WCS


@dataclass(frozen=True)
class Grid:
    ra: float
    dec: float
    npix: int               # odd, so the centre is a pixel centre
    scale_arcsec: float

    @property
    def shape(self) -> tuple[int, int]:
        return self.npix, self.npix

    @property
    def center_pix(self) -> float:
        return (self.npix - 1) / 2.0  # 0-based

    @property
    def wcs(self) -> WCS:
        w = WCS(naxis=2)
        w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
        w.wcs.crval = [self.ra, self.dec]
        w.wcs.crpix = [self.center_pix + 1, self.center_pix + 1]  # FITS is 1-based
        s = self.scale_arcsec / 3600.0
        w.wcs.cdelt = [-s, s]
        w.wcs.radesys = "ICRS"
        return w

    def sky_to_pix(self, ra, dec) -> tuple[np.ndarray, np.ndarray]:
        x, y = self.wcs.world_to_pixel_values(ra, dec)
        return x, y

    def to_json(self) -> dict:
        return {"ra": self.ra, "dec": self.dec, "npix": self.npix,
                "scale_arcsec": self.scale_arcsec, "center_pix": self.center_pix}


def make_grid(ra: float, dec: float, fov_arcmin: float, scale_arcsec: float = 6.15) -> Grid:
    n = int(np.ceil(fov_arcmin * 60.0 / scale_arcsec))
    n = max(n, 5)
    if n % 2 == 0:
        n += 1
    return Grid(ra=ra, dec=dec, npix=n, scale_arcsec=scale_arcsec)


def cutout_size_deg(fov_arcmin: float, scale_arcsec: float = 6.15) -> float:
    """Native cutout size that covers the grid at any detector rotation (diagonal plus a
    few pixels of margin for interpolation)."""
    return fov_arcmin / 60.0 * np.sqrt(2.0) + 4 * scale_arcsec / 3600.0
