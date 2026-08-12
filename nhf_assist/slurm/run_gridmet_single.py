"""Run gridMET climate drivers for a single child model.

This is the HPC version — self-contained, no nhm-assist repo needed.
Called by the SLURM array job with the model name as an argument.

Usage:
    python run_gridmet_single.py MiddleWillamette
"""

import os
import sys
import pathlib as pl


def main():
    if len(sys.argv) < 2:
        print("Usage: python run_gridmet_single.py <model_name>")
        sys.exit(1)

    # Fix SSL on HPC: point Python's ssl module at system CA bundle
    # (conda's certifi doesn't include DOI intermediate certs)
    import ssl
    system_ca = "/etc/pki/tls/certs/ca-bundle.crt"
    if os.path.exists(system_ca):
        os.environ.setdefault("SSL_CERT_FILE", system_ca)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", system_ca)
        ssl._create_default_https_context = lambda: ssl.create_default_context(
            cafile=system_ca
        )

    MODEL_NAME = sys.argv[1]
    WORK_DIR = pl.Path(__file__).resolve().parent

    # --- Configuration ---
    GPKG_PATH = WORK_DIR / "domain_data" / MODEL_NAME / "GIS" / "model_layers.gpkg"
    GPKG_LAYER = "nhru"
    START_DATE = "1979-01-01"
    END_DATE = "2024-09-30"
    VARS = ["ppt", "tmin", "tmax"]
    OUT = WORK_DIR / "domain_data" / MODEL_NAME
    GRIDMET_WORK = OUT / "gridmet_work"
    GRIDMET_WORK.mkdir(parents=True, exist_ok=True)

    print(f"Model: {MODEL_NAME}")
    print(f"GPKG: {GPKG_PATH}")
    print(f"Period: {START_DATE} to {END_DATE}")
    print(f"Output: {OUT}")

    if not GPKG_PATH.exists():
        print(f"ERROR: Geopackage not found at {GPKG_PATH}")
        sys.exit(1)

    # --- Start Dask cluster (uses SLURM-allocated CPUs) ---
    import dask.distributed

    n_workers = int(os.environ.get("SLURM_CPUS_PER_TASK", 4))
    cluster = dask.distributed.LocalCluster(
        n_workers=n_workers, threads_per_worker=1, processes=True
    )
    client = dask.distributed.Client(cluster)
    print(f"Dask cluster: {n_workers} workers")

    # --- Run the gridMET processing ---
    from gridmet_core import run_gridmet_for_domain

    run_gridmet_for_domain(
        gpkg_path=GPKG_PATH,
        gpkg_layer=GPKG_LAYER,
        start_date=START_DATE,
        end_date=END_DATE,
        variables=VARS,
        output_dir=OUT,
        work_dir=GRIDMET_WORK,
    )

    client.close()
    cluster.close()
    print(f"Done: {MODEL_NAME}")


if __name__ == "__main__":
    main()
