#!/bin/bash
# =============================================================================
# resubmit_if_faster.sh JOBID [--apply]
#
# For a PENDING Slurm job, ask the scheduler (sbatch --test-only) when the same
# script would start under several node/task layouts, and swap the job for the
# best layout if it starts sufficiently earlier. Run it on a Hovenweep login
# node. It makes ONE pass and exits (no daemon); loop it from your own machine
# if you want it repeated (see the usage note at the bottom).
#
# Default is a DRY RUN: it prints the table and what it would do.
# Add --apply to actually submit the new job and cancel the old one.
#
# Order of operations with --apply: submit the new job FIRST, then cancel the
# old one only if the submit succeeded, so a failed submit never loses the job.
#
# Environment overrides (all optional):
#   TOTAL_TASKS     tasks wanted (1 manager + workers)          default 140
#   WORKER_MEM_GB   memory per worker (measured MaxRSS ~9 GB)    default 9
#   MGR_MARGIN_GB   extra per-node memory for the manager        default 7
#   TIME_LIMIT      --time for the new job                       default 01:30:00
#   MIN_GAIN_MIN    only swap if it starts at least this many    default 60
#                   minutes earlier than the current job
#   CANDIDATES      space-separated NODESxTASKS_PER_NODE list
#
# Per-node memory is  tasks_per_node * WORKER_MEM_GB + MGR_MARGIN_GB  (--mem).
# =============================================================================
set -u

JOBID="${1:?usage: resubmit_if_faster.sh JOBID [--apply]}"
APPLY=0
[[ "${2:-}" == "--apply" ]] && APPLY=1

TOTAL_TASKS="${TOTAL_TASKS:-140}"
WORKER_MEM_GB="${WORKER_MEM_GB:-9}"
MGR_MARGIN_GB="${MGR_MARGIN_GB:-7}"
TIME_LIMIT="${TIME_LIMIT:-01:30:00}"
MIN_GAIN_MIN="${MIN_GAIN_MIN:-60}"
CANDIDATES="${CANDIDATES:-4x35 6x24 8x18 10x14 12x12 14x10 16x9 20x7 28x5}"

state="$(squeue -h -j "${JOBID}" -o %T 2>/dev/null)"
if [[ "${state}" != "PENDING" ]]; then
  echo "Job ${JOBID} is '${state:-not in queue}', not PENDING. Nothing to do."
  exit 0
fi

info="$(scontrol show job "${JOBID}")"
script="$(grep -oP 'Command=\K\S+' <<<"${info}")"
workdir="$(grep -oP 'WorkDir=\K\S+' <<<"${info}")"
[[ -f "${script}" ]] || { echo "Cannot find job script: ${script}"; exit 1; }
cd "${workdir}" || exit 1

now=$(date +%s)
cur_str="$(squeue -h --start -j "${JOBID}" -o %S)"
if [[ -z "${cur_str}" || "${cur_str}" == "N/A" ]]; then
  cur=$((now + 172800))   # no estimate yet: treat as 2 days out
else
  cur=$(date -d "${cur_str}" +%s)
fi
echo "Job ${JOBID}: script ${script}"
echo "Current estimated start: ${cur_str:-N/A}"
echo
printf '%-8s %-8s %-8s %-22s %s\n' "layout" "mem" "tasks" "est. start" "vs current"

best_e=""; best_opts=""; best_name=""
for c in ${CANDIDATES}; do
  n="${c%x*}"; t="${c#*x}"
  (( n * t >= TOTAL_TASKS )) || continue
  mem=$(( t * WORKER_MEM_GB + MGR_MARGIN_GB ))
  opts="-N ${n} --ntasks-per-node=${t} --mem=${mem}G --time=${TIME_LIMIT}"
  out="$(sbatch --test-only ${opts} "${script}" 2>&1)"
  st="$(sed -n 's/.*to start at \([^ ]*\) using.*/\1/p' <<<"${out}" | head -1)"
  if [[ -z "${st}" ]]; then
    printf '%-8s %-8s %-8s %-22s %s\n' "${n}x${t}" "${mem}G" "$((n*t))" "(failed)" "${out##*$'\n'}"
    continue
  fi
  e=$(date -d "${st}" +%s)
  gain=$(( (cur - e) / 60 ))
  printf '%-8s %-8s %-8s %-22s %+d min\n' "${n}x${t}" "${mem}G" "$((n*t))" "${st}" "${gain}"
  if [[ -z "${best_e}" || "${e}" -lt "${best_e}" ]]; then
    best_e="${e}"; best_opts="${opts}"; best_name="${n}x${t}"
  fi
done

echo
[[ -n "${best_e}" ]] || { echo "No candidate produced an estimate. Keeping job ${JOBID}."; exit 0; }
gain=$(( (cur - best_e) / 60 ))
if (( gain >= 0 )); then
  echo "Best layout: ${best_name} (${best_opts}), ${gain} min earlier than the current estimate."
else
  echo "Best layout: ${best_name} (${best_opts}), $(( -gain )) min later than the current estimate."
fi

if (( gain < MIN_GAIN_MIN )); then
  echo "Gain is below MIN_GAIN_MIN=${MIN_GAIN_MIN}. Keeping job ${JOBID}."
  exit 0
fi
if (( APPLY == 0 )); then
  echo "DRY RUN: would submit with these options, then cancel ${JOBID}. Re-run with --apply."
  exit 0
fi

newid="$(sbatch --parsable ${best_opts} "${script}")" || { echo "sbatch failed; job ${JOBID} kept."; exit 1; }
echo "Submitted ${newid}."
scancel "${JOBID}" && echo "Cancelled ${JOBID}."

# Usage from Windows PowerShell (one pass; loop it yourself if wanted):
#   ssh hw-login1 "bash /caldera/hovenweep/projects/usgs/water/wawsc/ahaj/resubmit_if_faster.sh 8028866"
# Repeating every 10 min until the job starts (stops when the job is no longer pending):
#   while ($true) { ssh hw-login1 "bash <path>/resubmit_if_faster.sh <jobid> --apply"; Start-Sleep 600 }
# After a swap, pass the NEW job id on the next pass.
