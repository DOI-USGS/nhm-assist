#!/bin/bash
# =============================================================================
# Submit gridMET array job to SLURM
# Run from the repo root on Hovenweep
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Create log directory
mkdir -p "${REPO_DIR}/nhf_assist/slurm_logs"

# Pre-flight checks
echo "=== Pre-flight checks ==="
echo "Repo: ${REPO_DIR}"
echo ""

# Check environment exists
if ! conda env list 2>/dev/null | grep -q "nhm-gridmet"; then
    echo "ERROR: 'nhm-gridmet' conda environment not found."
    echo "Run setup_hpc_env.sh first."
    exit 1
fi
echo "✓ Environment exists"

# Check domain data
MODELS=("MiddleWillamette" "NorthCoast_MidCoastA" "OwyheeRiver" "PowderRiver" 
        "SandyRiver" "SouthCoastB_LowerRogue" "UmatillaRiver" "UpperRogue" 
        "UpperUmpqua" "UpperWillamette")
MISSING=0
for m in "${MODELS[@]}"; do
    GPKG="${REPO_DIR}/nhf_assist/domain_data/${m}/GIS/model_layers.gpkg"
    if [ ! -f "${GPKG}" ]; then
        echo "✗ Missing: ${m}/GIS/model_layers.gpkg"
        MISSING=$((MISSING+1))
    fi
done
if [ ${MISSING} -eq 0 ]; then
    echo "✓ All ${#MODELS[@]} domain geopackages found"
else
    echo "WARNING: ${MISSING} geopackage(s) missing. Those tasks will fail."
fi
echo ""

# Submit
echo "=== Submitting SLURM array job ==="
sbatch "${SCRIPT_DIR}/gridmet_array_job.sh"
echo ""
echo "Monitor with: squeue -u \$USER"
echo "Logs in: nhf_assist/slurm_logs/"
