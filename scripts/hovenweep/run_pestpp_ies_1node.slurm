#!/bin/bash
# =============================================================================
# run_pestpp_ies_1node.slurm — SINGLE-NODE FALLBACK template for PEST++ IES.
#
# This is the KNOWN-GOOD, reliable config: 1 node, all tasks on it, the
# manager/worker handshake via $(hostname) (trivially routable within one node).
# NO cross-node TCP and NO preflight — none of the multi-node failure modes
# (fe80:: link-local hostname, cross-node routing, probe races) can occur here.
#
# Trade-off vs. the multi-node run_pestpp_ies.slurm: fewer workers (capped by
# one node's RAM) so more sequential waves and a longer wall time. But a single
# free node schedules FAST, and the run just works. Use this when you need a
# result reliably / today, or when the multi-node path is misbehaving.
#
# This is a reusable template. The 06 notebook substitutes <PLACEHOLDER> tokens
# and the SBATCH -n / --time / conda-dir values; or edit by hand.
# See scripts/hovenweep/README_hovenweep_run.md for the full workflow.
#
# Submit with:  sbatch run_pestpp_ies_1node.slurm
# =============================================================================
#SBATCH --job-name=<JOB_NAME>_1n                  # << distinct name so it won't clash with a multi-node job
#SBATCH --output=logs/%j-pestpp-ies-1node.out    # distinct log (logs/ must exist)
#SBATCH --account=<CENTER>                        # << edit: allocation (e.g. wawsc)
#SBATCH --partition=cpu                           # << edit: partition
#SBATCH -N 1                                      # ONE node: mgr/worker handshake via $(hostname), known-good
#SBATCH -n 27                                     # << 1 manager + N-1 workers, sized from node RAM (see 06 notebook)
#SBATCH --mem=0                                    # claim the whole node's RAM (workers are RAM-limited; avoids OOM from competition)
#SBATCH --hint=nomultithread
#SBATCH --time=04:00:00                           # << edit: walltime (48h max). Single node is slower — leave cushion.
#SBATCH --mail-type=ALL
#SBATCH --mail-user=<USER>@usgs.gov              # << edit: email

set -euo pipefail

# --- CONFIG (edit per run) -------------------------------------------------
PESTPP_MODULE="pestpp/5.2.19"
CONDA_DIR="/home/${USER}/miniforge3"              # << edit if conda is elsewhere
ENV_NAME="<PYWATERSHED_ENV>"                      # << edit: conda env w/ pywatershed
CASE_NAME="<CASE_NAME>"                            # << edit: <CASE_NAME>.pst in this dir
JOB_TAG="<JOB_NAME>_1n"                            # << edit: scratch dir tag (match job-name)
SCRATCH_BASE="/caldera/hovenweep/projects/usgs/water/<CENTER>/${USER}/scratch"  # << edit CENTER

# --- Modules + Python env --------------------------------------------------
# Use the LINUX pestpp-ies SHIPPED in the run dir (downloaded by the 06 notebook
# via pyemu get_pestpp, ostag=linux), not `module load`, so the run uses the
# exact release we packaged. Module load left as a commented fallback.
# module load "${PESTPP_MODULE}"
source "${CONDA_DIR}/etc/profile.d/conda.sh"
conda activate "${ENV_NAME}"

# System CA bundle (DOI certs) rather than conda's certifi.
export SSL_CERT_FILE=/etc/pki/tls/certs/ca-bundle.crt
export REQUESTS_CA_BUNDLE=/etc/pki/tls/certs/ca-bundle.crt
export OMP_NUM_THREADS=1                           # 1 thread/pywatershed process

# --- Derived ---------------------------------------------------------------
TEMPLATE_DIR="${SLURM_SUBMIT_DIR}"                 # pristine, shared run dir
# Absolute path to the shipped Linux binary (manager + workers use the same exe).
PEST_VER="${TEMPLATE_DIR}/pestpp-ies"
chmod +x "${PEST_VER}" 2>/dev/null || true
SCRATCH_DIR="${SCRATCH_BASE}/${JOB_TAG}_${SLURM_JOBID}"
WORKER_PREFIX="${SCRATCH_DIR}/agent_"
BASE_PORT=$((10000 + RANDOM % 20000))
# Single node: the short hostname is trivially routable to itself, so $(hostname)
# is the known-good choice here (no cross-node fabric involved). This is the key
# difference from the multi-node script, which must use `hostname -f`.
MANAGER_HOST="$(hostname)"

mkdir -p "${SCRATCH_DIR}"
chmod +x "${TEMPLATE_DIR}/setup_worker.sh"

# --- Build worker dirs up front (parallel across ranks) --------------------
echo "Setting up worker directories in ${SCRATCH_DIR} ..."
srun "${TEMPLATE_DIR}/setup_worker.sh" "${TEMPLATE_DIR}" "${WORKER_PREFIX}"
echo "Worker directories ready."

echo "=============================================================="
echo "PEST++ IES run (SINGLE-NODE FALLBACK)"
echo "  case         : ${CASE_NAME}.pst"
echo "  template dir : ${TEMPLATE_DIR}"
echo "  scratch dir  : ${SCRATCH_DIR}"
echo "  tasks (-n)   : ${SLURM_NTASKS}  (1 manager + $((SLURM_NTASKS-1)) workers)"
echo "  manager host : ${MANAGER_HOST}   port: ${BASE_PORT}"
echo "  pestpp-ies   : $(command -v ${PEST_VER})"
echo "  python       : $(command -v python)  (pywatershed $(python -c 'import pywatershed as p; print(p.__version__)'))"
echo "=============================================================="

# --- srun multi-prog config ------------------------------------------------
# Rank 0 = manager (runs in TEMPLATE_DIR, where outputs land).
# Ranks 1..N-1 = workers (cd into their pre-built scratch dir, connect back).
CONF_FILE="${TEMPLATE_DIR}/pestpp_ies_1node_${SLURM_JOBID}.conf"
# stdbuf -oL -eL forces LINE-buffered stdout so manager setup lines appear in
# the log LIVE, not only on a block-buffer flush (otherwise it can look hung).
{
  echo "0 bash -c 'cd ${TEMPLATE_DIR} && stdbuf -oL -eL ${PEST_VER} ${CASE_NAME}.pst /h :${BASE_PORT} > logs/manager_1node.out 2>&1'"
  echo "1-$((SLURM_NTASKS-1)) bash -c 'cd ${WORKER_PREFIX}\${SLURM_PROCID} && stdbuf -oL -eL ${PEST_VER} ${CASE_NAME}.pst /h ${MANAGER_HOST}:${BASE_PORT} > worker.out 2>&1'"
} > "${CONF_FILE}"

echo "srun --multi-prog ${CONF_FILE}"
srun --multi-prog "${CONF_FILE}"

echo "=============================================================="
echo "PEST++ IES finished (single-node)."
echo "  Manager outputs (${CASE_NAME}.*) : ${TEMPLATE_DIR}"
echo "  Worker scratch (disposable)      : ${SCRATCH_DIR}"
echo "  Reclaim space:  rm -rf ${SCRATCH_DIR}"
echo "=============================================================="
