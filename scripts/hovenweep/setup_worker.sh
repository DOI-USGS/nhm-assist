#!/bin/bash
# =============================================================================
# setup_worker.sh — TEMPLATE: build ONE PEST++ IES worker directory in scratch.
#
# Launched once per rank via `srun setup_worker.sh <TEMPLATE_DIR> <WORKER_PREFIX>`;
# each rank derives its own dir from $SLURM_PROCID. COPIES the small run files
# and SYMLINKS the large read-only inputs (climate + observation NetCDFs) so N
# workers use a few GB of scratch instead of tens of GB.
#
# Adapt COPY_FILES / SYMLINK_FILES to YOUR run's file names (the defaults below
# match the CrookedRiver pywatershed IES layout). Rule of thumb:
#   - COPY   : anything written per realization + small control/data files
#   - SYMLINK: large, read-only inputs (climate .nc, observation_data/, etc.)
#
# Args:
#   $1 TEMPLATE_DIR   : pristine, shared run directory (on /caldera)
#   $2 WORKER_PREFIX  : worker dir prefix; this rank uses ${PREFIX}${SLURM_PROCID}
# =============================================================================

set -euo pipefail

TEMPLATE_DIR="$1"
WORKER_DIR="${2}${SLURM_PROCID}"

# PEST++ case name — the <CASE_NAME>.pst and its external data csvs.
# << edit: set to your .pst case name.
CASE_NAME="<CASE_NAME>"

# Large, read-only inputs -> symlink. << edit for your climate input file names.
SYMLINK_FILES=(
    "prcp.nc"
    "tmax.nc"
    "tmin.nc"
)

# Small run files each worker needs -> copy.
COPY_FILES=(
    "${CASE_NAME}.pst"
    "${CASE_NAME}.pargp_data.csv"
    "${CASE_NAME}.par_data.csv"
    "${CASE_NAME}.obs_data.csv"
    "${CASE_NAME}.tplfile_data.csv"
    "${CASE_NAME}.insfile_data.csv"
    "parameters.json"
    "parameters.json.tpl"
    "modelobs.dat"
    "modelobs.dat.ins"
    "control.default.bandit"
    "forward_run.py"
    "loc.mat"
    "phi_factors.csv"
    "starting_par_vals.dat"
)

mkdir -p "${WORKER_DIR}/output"

for f in "${COPY_FILES[@]}"; do
    [[ -e "${TEMPLATE_DIR}/${f}" ]] && cp -f "${TEMPLATE_DIR}/${f}" "${WORKER_DIR}/${f}"
done

for f in "${SYMLINK_FILES[@]}"; do
    [[ -e "${TEMPLATE_DIR}/${f}" ]] && ln -sf "${TEMPLATE_DIR}/${f}" "${WORKER_DIR}/${f}"
done

# Read-only NetCDF/CSV directories: symlink the whole dir.
[[ -d "${TEMPLATE_DIR}/observation_data" ]] && ln -sfn "${TEMPLATE_DIR}/observation_data" "${WORKER_DIR}/observation_data"
[[ -d "${TEMPLATE_DIR}/ancillary" ]] && ln -sfn "${TEMPLATE_DIR}/ancillary" "${WORKER_DIR}/ancillary"

if [ $? -ne 0 ]; then
    echo "Setting up worker directory ${WORKER_DIR} failed!!"
    exit 255
fi
exit 0
