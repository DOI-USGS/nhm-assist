"""Run gridMET climate drivers for all child models sequentially.

Use this on Hovenweep's JupyterHub (which has internet access)
instead of SLURM compute nodes (which are firewalled).

Usage:
    python run_all_models.py

Or from a Jupyter notebook cell:
    %run run_all_models.py
"""

import os
import sys
import time
import pathlib as pl

# Fix SSL on HPC: use system CA bundle (includes DOI certs)
import ssl

system_ca = "/etc/pki/tls/certs/ca-bundle.crt"
if os.path.exists(system_ca):
    os.environ.setdefault("SSL_CERT_FILE", system_ca)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", system_ca)
    ssl._create_default_https_context = lambda: ssl.create_default_context(
        cafile=system_ca
    )

WORK_DIR = pl.Path(__file__).resolve().parent

CHILD_MODELS = [
    "MiddleWillamette",
    "NorthCoast_MidCoastA",
    "OwyheeRiver",
    "PowderRiver",
    "SandyRiver",
    "SouthCoastB_LowerRogue",
    "UmatillaRiver",
    "UpperRogue",
    "UpperUmpqua",
    "UpperWillamette",
]

GPKG_LAYER = "nhru"
START_DATE = "1979-01-01"
END_DATE = "2024-09-30"
VARS = ["ppt", "tmin", "tmax"]


def main():
    from gridmet_core import run_gridmet_for_domain

    print("=" * 70)
    print(f"GridMET Climate Drivers — Processing {len(CHILD_MODELS)} models")
    print(f"Work dir: {WORK_DIR}")
    print(f"Period: {START_DATE} to {END_DATE}")
    print("=" * 70)

    results = {}
    total_start = time.time()

    for i, model in enumerate(CHILD_MODELS):
        print(f"\n{'='*70}")
        print(f"[{i+1}/{len(CHILD_MODELS)}] {model}")
        print(f"{'='*70}")

        gpkg_path = WORK_DIR / "domain_data" / model / "GIS" / "model_layers.gpkg"
        output_dir = WORK_DIR / "domain_data" / model
        work_dir = output_dir / "gridmet_work"
        work_dir.mkdir(parents=True, exist_ok=True)

        if not gpkg_path.exists():
            print(f"  SKIPPED: Geopackage not found at {gpkg_path}")
            results[model] = "SKIPPED"
            continue

        model_start = time.time()
        try:
            run_gridmet_for_domain(
                gpkg_path=gpkg_path,
                gpkg_layer=GPKG_LAYER,
                start_date=START_DATE,
                end_date=END_DATE,
                variables=VARS,
                output_dir=output_dir,
                work_dir=work_dir,
            )
            elapsed = time.time() - model_start
            print(f"  COMPLETED in {elapsed/60:.1f} min")
            results[model] = f"OK ({elapsed/60:.1f} min)"
        except Exception as e:
            elapsed = time.time() - model_start
            print(f"  FAILED after {elapsed/60:.1f} min: {e}")
            results[model] = f"FAILED: {e}"

    total_elapsed = time.time() - total_start

    print(f"\n{'='*70}")
    print(f"SUMMARY — Total time: {total_elapsed/60:.1f} min")
    print(f"{'='*70}")
    for model, status in results.items():
        print(f"  {model:30s} {status}")

    # Count successes
    ok_count = sum(1 for v in results.values() if v.startswith("OK"))
    print(f"\n  {ok_count}/{len(CHILD_MODELS)} models completed successfully.")


if __name__ == "__main__":
    main()
