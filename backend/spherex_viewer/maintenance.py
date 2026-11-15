"""Cache maintenance.

    python -m spherex_viewer.maintenance slim-cache [--workers N]
        Strip the detector-wide EPSF table from cached cutouts (keeps the PSFs nearest
        each cutout). Cutouts fetched by current versions are already slim.
    python -m spherex_viewer.maintenance stats
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from .config import settings
from .data_access.fitsmeta import slim_file


def _slim(path: str) -> int:
    try:
        return slim_file(Path(path))
    except Exception as e:  # noqa: BLE001 - report and continue
        print(f"skip {path}: {e}")
        return 0


def cutout_files() -> list[str]:
    return [str(p) for p in (settings.cache_dir / "cutouts").rglob("*.fits")]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["slim-cache", "stats"])
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    files = cutout_files()
    total = sum(Path(f).stat().st_size for f in files)
    print(f"{len(files)} cached cutouts, {total / 1e9:.2f} GB in {settings.cache_dir / 'cutouts'}")
    if args.command == "slim-cache":
        saved = 0
        with ProcessPoolExecutor(args.workers) as ex:
            for i, n in enumerate(ex.map(_slim, files, chunksize=32), 1):
                saved += n
                if i % 500 == 0:
                    print(f"  {i}/{len(files)} processed, {saved / 1e9:.2f} GB freed so far", flush=True)
        print(f"freed {saved / 1e9:.2f} GB; cache is now {(total - saved) / 1e9:.2f} GB")


if __name__ == "__main__":
    main()
