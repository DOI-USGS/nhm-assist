"""Count HRUs in each subdomain model's geopackage.

Scans a domain-data root folder, finds every model geopackage, reads the
`nhru` layer, and prints a table of domain name -> HRU count to the console.

Geopackage locations handled:
    <root>/<domain>/GIS/model_layers.gpkg   (standard NHM subdomain layout)
    <root>/<domain>/model_layers.gpkg        (some domains, e.g. OHM)

Usage:
    pixi run python scripts/count_domain_hrus.py
    pixi run python scripts/count_domain_hrus.py --root domain_data
    pixi run python scripts/count_domain_hrus.py --root nhf_assist/domain_data
    pixi run python scripts/count_domain_hrus.py --layer nhru --gpkg-name model_layers.gpkg
"""

from __future__ import annotations

import argparse
import pathlib as pl

from rich.console import Console
from rich.table import Table

# pyogrio ships with geopandas and lets us read layer info / counts without
# loading geometry. Fall back to geopandas if the fast path is unavailable.
try:
    from pyogrio import list_layers, read_info

    _HAVE_PYOGRIO = True
except Exception:  # pragma: no cover
    _HAVE_PYOGRIO = False

import geopandas as gpd

console = Console()

DEFAULT_ROOT = "domain_data"
DEFAULT_GPKG_NAME = "model_layers.gpkg"
DEFAULT_LAYER = "nhru"


def find_geopackages(root: pl.Path, gpkg_name: str) -> list[pl.Path]:
    """Return all matching geopackages under root (any depth), sorted."""
    return sorted(root.rglob(gpkg_name))


def domain_name_for(gpkg: pl.Path, root: pl.Path) -> str:
    """Derive the domain name from a geopackage path.

    Uses the first path component under `root` as the domain name, which works
    for both `<domain>/GIS/model_layers.gpkg` and `<domain>/model_layers.gpkg`.
    """
    try:
        rel = gpkg.relative_to(root)
        return rel.parts[0] if rel.parts else gpkg.parent.name
    except ValueError:
        return gpkg.parent.name


def count_hrus(gpkg: pl.Path, layer: str) -> tuple[int | None, str]:
    """Return (hru_count, note). count is None if the layer is missing/unreadable."""
    if _HAVE_PYOGRIO:
        try:
            available = {name for name, _geom in list_layers(gpkg)}
            if layer not in available:
                return None, f"no '{layer}' layer (has: {', '.join(sorted(available)) or 'none'})"
            info = read_info(gpkg, layer=layer)
            return int(info["features"]), ""
        except Exception as exc:  # fall through to geopandas
            note = f"pyogrio failed ({exc}); "
    else:
        note = ""

    # Fallback: read the layer with geopandas (loads geometry, slower).
    try:
        gdf = gpd.read_file(gpkg, layer=layer)
        return len(gdf), note.strip("; ")
    except Exception as exc:
        return None, f"{note}read failed: {exc}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=DEFAULT_ROOT,
        help=f"Domain-data root folder to scan (default: {DEFAULT_ROOT}).",
    )
    parser.add_argument(
        "--gpkg-name",
        default=DEFAULT_GPKG_NAME,
        help=f"Geopackage filename to look for (default: {DEFAULT_GPKG_NAME}).",
    )
    parser.add_argument(
        "--layer",
        default=DEFAULT_LAYER,
        help=f"HRU layer name to count (default: {DEFAULT_LAYER}).",
    )
    args = parser.parse_args()

    root = pl.Path(args.root).resolve()
    if not root.is_dir():
        console.print(f"[red]Root folder not found:[/red] {root}")
        return

    gpkgs = find_geopackages(root, args.gpkg_name)
    if not gpkgs:
        console.print(
            f"[yellow]No '{args.gpkg_name}' files found under[/yellow] {root}"
        )
        return

    rows: list[tuple[str, int | None, str]] = []
    for gpkg in gpkgs:
        domain = domain_name_for(gpkg, root)
        count, note = count_hrus(gpkg, args.layer)
        rows.append((domain, count, note))

    # Sort by HRU count (descending), missing counts last.
    rows.sort(key=lambda r: (r[1] is None, -(r[1] or 0)))

    table = Table(
        title=f"HRU counts ('{args.layer}' layer) under {root}",
        header_style="bold",
    )
    table.add_column("Domain", style="cyan", no_wrap=True)
    table.add_column("HRU count", justify="right", style="green")
    table.add_column("Note", style="dim")

    total = 0
    counted = 0
    for domain, count, note in rows:
        if count is None:
            table.add_row(domain, "[red]—[/red]", note)
        else:
            table.add_row(domain, f"{count:,}", note)
            total += count
            counted += 1

    if counted:
        table.add_section()
        table.add_row(
            f"[bold]TOTAL ({counted} model{'s' if counted != 1 else ''})[/bold]",
            f"[bold]{total:,}[/bold]",
            "",
        )

    console.print(table)


if __name__ == "__main__":
    main()
