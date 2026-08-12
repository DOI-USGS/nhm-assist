#!/bin/bash
# =============================================================================
# One-time HPC environment setup for nhm-assist gridMET drivers
# Run this once on Hovenweep to create the conda environment
# =============================================================================

ENV_NAME="nhm-gridmet"
CONDA_DIR="${HOME}/miniforge3"

echo "Setting up ${ENV_NAME} environment on $(hostname)..."

# Check if miniforge exists
if [ ! -d "${CONDA_DIR}" ]; then
    echo "ERROR: miniforge3 not found at ${CONDA_DIR}"
    echo "Install miniforge first: https://github.com/conda-forge/miniforge"
    exit 1
fi

source "${CONDA_DIR}/etc/profile.d/conda.sh"

# Check if env already exists
if conda env list | grep -q "${ENV_NAME}"; then
    echo "Environment '${ENV_NAME}' already exists. Updating..."
    conda env update -n "${ENV_NAME}" -f environment_hpc.yml
else
    echo "Creating environment '${ENV_NAME}'..."
    conda env create -f environment_hpc.yml
fi

# Verify key packages
conda activate "${ENV_NAME}"
echo ""
echo "Verifying packages..."
python -c "import gdptools; print(f'gdptools: {gdptools.__version__}')"
python -c "import xarray; print(f'xarray: {xarray.__version__}')"
python -c "import geopandas; print(f'geopandas: {geopandas.__version__}')"
python -c "import rioxarray; print('rioxarray: OK')"
python -c "import dask; print(f'dask: {dask.__version__}')"

echo ""
echo "Environment setup complete!"
echo "To activate: conda activate ${ENV_NAME}"
