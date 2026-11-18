#!/bin/bash
# =============================================================================
# run_pestpp_ies.slurm — TEMPLATE for a parallel PEST++ IES run on Hovenweep.
#
# This is a reusable template. Edit the #SBATCH lines and the CONFIG block below
# for your run (or keep them in sync with scripts/hovenweep/hovenweep_config.env).
# See scripts/hovenweep/README_hovenweep_run.md for the full workflow.
#
# Model: pywatershed forward model (forward_run.py). Parallelism: srun
# --multi-prog with 1 manager (rank 0) + N-1 workers. Workers run in per-worker
# scratch dirs built by setup_worker.sh (small files copied, big read-only
# NetCDFs symlinked).
# =============================================================================
#SBATCH --job-name=<JOB_NAME>                    # << edit: job name
#SBATCH --output=logs/%j-pestpp-ies.out          # log (logs/ must exist)
#SBATCH --account=<CENTER>                        # << edit: allocation (e.g. wawsc)
#SBATCH --partition=cpu                           # << edit: partition
#SBATCH -N <NODES>                                # << nodes. Multi-node OK: workers dial manager FQDN over IB fabric (verified cn131<->cn132)
#SBATCH --ntasks-per-node=<TASKS_PER_NODE>        # << set by 06 notebook: workers/node, RAM-limited (512GB/node). Total tasks = N * this
#SBATCH --mem=330G                                # claim the whole node's RAM (workers are RAM-limited; avoids OOM from competition)
#SBATCH --hint=nomultithread
#SBATCH --time=04:00:00                           # << edit: walltime (48h max)
#SBATCH --mail-type=ALL
#SBATCH --mail-user=<USER>@usgs.gov              # << edit: email

set -euo pipefail

# --- CONFIG (edit per run) -------------------------------------------------
PESTPP_MODULE="pestpp/5.2.19"
CONDA_DIR="/home/${USER}/miniforge3"              # << edit if conda is elsewhere
ENV_NAME="<PYWATERSHED_ENV>"                      # << edit: conda env w/ pywatershed
CASE_NAME="<CASE_NAME>"                            # << edit: <CASE_NAME>.pst in this dir
JOB_TAG="<JOB_NAME>"                               # << edit: scratch dir tag (match job-name)
SCRATCH_BASE="/caldera/hovenweep/projects/usgs/water/<CENTER>/${USER}/scratch"  # << edit CENTER

# --- Modules + Python env --------------------------------------------------
# NOTE: we use the LINUX pestpp-ies SHIPPED in the run dir (downloaded by the
# 06 notebook via pyemu get_pestpp, ostag=linux) rather than `module load`, so
# the run uses the exact release we packaged. The module load is left as a
# commented fallback if the shipped binary is ever missing.
# module load "${PESTPP_MODULE}"
source "${CONDA_DIR}/etc/profile.d/conda.sh"
conda activate "${ENV_NAME}"

# System CA bundle (DOI certs) rather than conda's certifi.
export SSL_CERT_FILE=/etc/pki/tls/certs/ca-bundle.crt
export REQUESTS_CA_BUNDLE=/etc/pki/tls/certs/ca-bundle.crt
export OMP_NUM_THREADS=1                           # 1 thread/pywatershed process

# --- Derived ---------------------------------------------------------------
TEMPLATE_DIR="${SLURM_SUBMIT_DIR}"                 # pristine, shared run dir
# Absolute path to the shipped Linux binary so BOTH the manager (runs in
# TEMPLATE_DIR) and the workers (cd into scratch dirs) invoke the same exe.
PEST_VER="${TEMPLATE_DIR}/pestpp-ies"
chmod +x "${PEST_VER}" 2>/dev/null || true
SCRATCH_DIR="${SCRATCH_BASE}/${JOB_TAG}_${SLURM_JOBID}"
WORKER_PREFIX="${SCRATCH_DIR}/agent_"
BASE_PORT=$((10000 + RANDOM % 20000))
# Use the FULLY-QUALIFIED name (cnNNN.ib0.cm.cr.usgs.gov). The short name can
# resolve to an unroutable IPv6 link-local (fe80::) on some nodes, which makes
# workers on OTHER nodes silently fail to connect back to the manager. The FQDN
# resolves to the routable InfiniBand-fabric IPv4 (verified cn131<->cn132).
MANAGER_HOST="$(hostname -f)"

mkdir -p "${SCRATCH_DIR}"
chmod +x "${TEMPLATE_DIR}/setup_worker.sh"

# --- Build worker dirs up front (parallel across ranks) --------------------
echo "Setting up worker directories in ${SCRATCH_DIR} ..."
srun "${TEMPLATE_DIR}/setup_worker.sh" "${TEMPLATE_DIR}" "${WORKER_PREFIX}"
echo "Worker directories ready."

echo "=============================================================="
echo "PEST++ IES run"
echo "  case         : ${CASE_NAME}.pst"
echo "  template dir : ${TEMPLATE_DIR}"
echo "  scratch dir  : ${SCRATCH_DIR}"
echo "  tasks (-n)   : ${SLURM_NTASKS}  (1 manager + $((SLURM_NTASKS-1)) workers)"
echo "  manager host : ${MANAGER_HOST}   port: ${BASE_PORT}"
echo "  pestpp-ies   : $(command -v ${PEST_VER})"
echo "  python       : $(command -v python)  (pywatershed $(python -c 'import pywatershed as p; print(p.__version__)'))"
echo "  nodes        : $(scontrol show hostnames "${SLURM_NODELIST}" | tr '\n' ' ')"
echo "=============================================================="

# --- Preflight: confirm workers can reach the manager over TCP -------------
# Multi-node PEST++ hangs SILENTLY if a worker node can't open a TCP connection
# back to the manager's advertised host:port (the fe80:: link-local trap). Test
# it here so a networking problem fails FAST and LOUD instead of looking hung.
#
# CRITICAL: run EXACTLY ONE probe task per node. A plain `srun` inherits the
# job's full task count (e.g. 140) and Slurm IGNORES a bare --ntasks-per-node=1,
# so 140 tasks stampede one listener and mostly get spurious connection-refused.
# Pin --ntasks to the node count AND --ntasks-per-node=1 (+ --overcommit) so the
# layout is honored. The listener uses `nc -k` (persistent: keeps accepting) so
# there is no accept-race; each worker node connects once.
PREFLIGHT_PORT=$((BASE_PORT + 1))   # separate port from the real run
echo "Preflight: 1 probe/node -> ${MANAGER_HOST}:${PREFLIGHT_PORT} (nodes=${SLURM_NNODES}) ..."
set +e
srun --nodes="${SLURM_NNODES}" --ntasks="${SLURM_NNODES}" --ntasks-per-node=1 --overcommit \
  bash -c '
    port='"${PREFLIGHT_PORT}"'
    mgr="'"${MANAGER_HOST}"'"
    if [[ "$(hostname -f)" == "$mgr" ]]; then
      # Manager node: persistent listener that accepts every worker connection.
      timeout 25 nc -k -l "$port" >/dev/null 2>&1 &
      lpid=$!
      sleep 22
      kill "$lpid" 2>/dev/null
      exit 0
    else
      sleep 4   # let the listener come up
      if command -v nc >/dev/null 2>&1; then
        probe() { echo ping | timeout 8 nc "$mgr" "$port" >/dev/null 2>&1; }
      else
        probe() { timeout 8 bash -c ": > /dev/tcp/$mgr/$port" >/dev/null 2>&1; }
      fi
      for attempt in 1 2 3 4 5; do
        if probe; then echo "  [$(hostname)] TCP OK -> $mgr"; exit 0; fi
        sleep 2
      done
      echo "  [$(hostname)] TCP FAILED -> $mgr:$port (5 attempts)" >&2
      exit 17
    fi'
preflight_rc=$?
set -e
if [[ "${preflight_rc}" -ne 0 ]]; then
  echo "PREFLIGHT FAILED (rc=${preflight_rc}): a worker node could not reach the manager" >&2
  echo "  at ${MANAGER_HOST}:${PREFLIGHT_PORT} after retries. Workers cannot connect back;" >&2
  echo "  aborting before the run hangs. Check hostname -f resolves to a routable IB IP" >&2
  echo "  on every node, and that outbound TCP to that port is allowed." >&2
  exit 17
fi
echo "Preflight OK: all worker nodes can reach the manager."
echo "=============================================================="

# --- srun multi-prog config ------------------------------------------------
# Rank 0 = manager (runs in TEMPLATE_DIR, where outputs land).
# Ranks 1..N-1 = workers (cd into their pre-built scratch dir, connect back).
CONF_FILE="${TEMPLATE_DIR}/pestpp_ies_${SLURM_JOBID}.conf"
# stdbuf -oL -eL forces LINE-buffered stdout so manager setup lines appear in
# logs/manager.out LIVE, not only on a block-buffer flush. Without it the log
# can sit at "processing control file" for many minutes while the manager is
# actually working — which looks like a hang.
{
  echo "0 bash -c 'cd ${TEMPLATE_DIR} && stdbuf -oL -eL ${PEST_VER} ${CASE_NAME}.pst /h :${BASE_PORT} > logs/manager.out 2>&1'"
  echo "1-$((SLURM_NTASKS-1)) bash -c 'cd ${WORKER_PREFIX}\${SLURM_PROCID} && stdbuf -oL -eL ${PEST_VER} ${CASE_NAME}.pst /h ${MANAGER_HOST}:${BASE_PORT} > worker.out 2>&1'"
} > "${CONF_FILE}"

echo "srun --multi-prog ${CONF_FILE}"
srun --multi-prog "${CONF_FILE}"

echo "=============================================================="
echo "PEST++ IES finished."
echo "  Manager outputs (${CASE_NAME}.*) : ${TEMPLATE_DIR}"
echo "  Worker scratch (disposable)      : ${SCRATCH_DIR}"
echo "  Reclaim space:  rm -rf ${SCRATCH_DIR}"
echo "=============================================================="
