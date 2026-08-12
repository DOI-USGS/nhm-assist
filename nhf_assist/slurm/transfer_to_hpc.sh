#!/bin/bash
# =============================================================================
# Transfer gridMET driver files to Hovenweep
# Run this locally (from nhf_assist/slurm/)
# =============================================================================

# Load config
if [ -f .env.hovenweep ]; then
    source .env.hovenweep
else
    echo "ERROR: .env.hovenweep not found."
    echo "Copy .env.hovenweep.template to .env.hovenweep and fill in your values."
    exit 1
fi

echo "=== Transferring gridMET driver files to ${HPC_HOST} ==="
echo "Target: ${HPC_WORK_DIR}"
echo ""

# Create remote directory structure
ssh ${HPC_USER}@${HPC_HOST} "mkdir -p ${HPC_WORK_DIR}/{logs,domain_data}"

# Transfer scripts
echo "Transferring scripts..."
scp gridmet_array_job.sh ${HPC_USER}@${HPC_HOST}:${HPC_WORK_DIR}/
scp run_gridmet_single.py ${HPC_USER}@${HPC_HOST}:${HPC_WORK_DIR}/
scp gridmet_core.py ${HPC_USER}@${HPC_HOST}:${HPC_WORK_DIR}/
scp environment_hpc.yml ${HPC_USER}@${HPC_HOST}:${HPC_WORK_DIR}/
scp setup_hpc_env.sh ${HPC_USER}@${HPC_HOST}:${HPC_WORK_DIR}/

# Transfer domain geopackages
echo ""
echo "Transferring domain geopackages..."
MODELS=("MiddleWillamette" "NorthCoast_MidCoastA" "OwyheeRiver" "PowderRiver" 
        "SandyRiver" "SouthCoastB_LowerRogue" "UmatillaRiver" "UpperRogue" 
        "UpperUmpqua" "UpperWillamette")

for m in "${MODELS[@]}"; do
    LOCAL_DIR="../domain_data/${m}/GIS"
    if [ -d "${LOCAL_DIR}" ]; then
        echo "  ${m}..."
        ssh ${HPC_USER}@${HPC_HOST} "mkdir -p ${HPC_WORK_DIR}/domain_data/${m}/GIS"
        scp ${LOCAL_DIR}/model_layers.gpkg ${HPC_USER}@${HPC_HOST}:${HPC_WORK_DIR}/domain_data/${m}/GIS/
    else
        echo "  [SKIP] ${m} — local GIS folder not found"
    fi
done

echo ""
echo "=== Transfer complete ==="
echo ""
echo "Next steps on Hovenweep:"
echo "  ssh ${HPC_USER}@${HPC_HOST}"
echo "  cd ${HPC_WORK_DIR}"
echo "  bash setup_hpc_env.sh        # one-time env setup"
echo "  sbatch gridmet_array_job.sh  # submit jobs"
echo "  squeue -u \$USER              # monitor"
