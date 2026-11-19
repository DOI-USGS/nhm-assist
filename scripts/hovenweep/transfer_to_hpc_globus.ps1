# =============================================================================
# transfer_to_hpc_globus.ps1 — TEMPLATE: transfer a PEST++ IES run dir to
# Hovenweep using the GLOBUS CLI (preferred over scp for large / many files).
#
# Why Globus over scp: it uses the DTN-backed endpoints, parallelizes, retries,
# resumes, and checksums — scp over a login node does none of that and is
# discouraged for multi-GB transfers (the run ships ~0.5 GB of NetCDFs).
#
# PREREQS (one-time):
#   1. Install the Globus CLI where you run this (conda-forge):
#        pixi run -e <ENV_WITH_GLOBUS> globus --version
#      (globus-cli is a CLI we invoke, NOT a Python import — install it in an
#       opt-in pixi feature/env, not [project.dependencies].)
#   2. globus login          # opens a browser; authenticate with USGS AD (PIV+MFA)
#   3. Install Globus Connect Personal on THIS workstation so your laptop is an
#      endpoint (https://www.globus.org/globus-connect-personal), start it, and
#      note its collection/endpoint UUID.
#   4. Find the Hovenweep endpoint UUID:
#        globus endpoint search "Hovenweep"
#      (ARC-managed "Hovenweep Disk Storage"; if it doesn't appear or won't
#       connect, email hpc@usgs.gov to map your login shortname to your Globus
#       identity.) Confirm the collection status before relying on it.
#
# Globus moves DATA ONLY. It cannot mkdir-then-chmod or fix CRLF line endings,
# so this script still makes ONE ssh -K call at the end to normalize the shell
# scripts (VPN + Kerberos required for that step, exactly like the scp version).
#
# See scripts/hovenweep/README_hovenweep_run.md for the full workflow.
# =============================================================================

$ErrorActionPreference = "Stop"

# --- CONFIG (edit per run) -------------------------------------------------
$hpcUser   = "<HPC_USER>"                 # your Hovenweep username
$center    = "<CENTER>"                   # your center allocation, e.g. wawsc
$remote    = "$hpcUser@hw-login1.gs.doi.net"
$caseName  = "<CASE_NAME>"                # <CASE_NAME>.pst

# Globus endpoint / collection UUIDs (from `globus endpoint search`):
$srcEndpoint = "<SRC_ENDPOINT_ID>"        # THIS workstation (Globus Connect Personal)
$dstEndpoint = "<DST_ENDPOINT_ID>"        # Hovenweep Disk Storage

# Paths. Globus paths are relative to each endpoint's configured root.
#  - $srcRoot: how the local run dir looks THROUGH Globus Connect Personal.
#    On Windows GCP a path like D:\foo is exposed as /D/foo (check your GCP
#    "Access" config for the exact mapping).
#  - $dstRoot: absolute path on Hovenweep.
$srcRoot   = "<GLOBUS_LOCAL_RUN_DIR>"     # e.g. /D/Projects/.../CrookedRiver/pestpp_ies
$dstRoot   = "/caldera/hovenweep/projects/usgs/water/$center/$hpcUser/<RUN_NAME>"

# --- Preflight -------------------------------------------------------------
Write-Host "=== Checking Globus CLI login ===" -ForegroundColor Cyan
globus whoami
if ($LASTEXITCODE -ne 0) {
    Write-Host "Not logged in. Run:  globus login" -ForegroundColor Red
    exit 1
}

# --- Transfer --------------------------------------------------------------
# One recursive, checksum-synced transfer of the whole run dir. Globus creates
# missing destination directories automatically. --sync-level checksum only
# moves new/changed files, so re-running is cheap (e.g. after editing the .slurm).
Write-Host "=== Submitting Globus transfer (recursive, checksum sync) ===" -ForegroundColor Cyan
Write-Host "  src: ${srcEndpoint}:${srcRoot}" -ForegroundColor Yellow
Write-Host "  dst: ${dstEndpoint}:${dstRoot}" -ForegroundColor Yellow

$label = "nhm-assist $caseName $(Get-Date -Format yyyyMMdd-HHmmss)"
# --exclude "*.exe": the Windows binaries are useless on Linux Hovenweep and we
# delete them there anyway. The run uses the LINUX pestpp-ies shipped in the run
# dir (downloaded by the 06 notebook), which IS transferred (no extension).
globus transfer "${srcEndpoint}:${srcRoot}" "${dstEndpoint}:${dstRoot}" `
    --recursive `
    --sync-level checksum `
    --exclude "*.exe" `
    --label $label `
    --notify off
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: globus transfer submission failed." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Transfer submitted. Track it with:" -ForegroundColor Cyan
Write-Host "  globus task list"
Write-Host "  globus task wait <TASK_ID>        # block until done"
Write-Host ""
Write-Host "WAIT for the transfer to COMPLETE before the fixup step below" -ForegroundColor Yellow
Write-Host "(the .slurm/.sh must exist on the cluster first)."
Write-Host ""

# --- Post-transfer fixup (needs VPN + Kerberos) ----------------------------
# Globus can't chmod or strip CRLF. Do it once the transfer completes.
$doFixup = Read-Host "Has the Globus transfer COMPLETED? Run line-ending/permission fixup now? (y/N)"
if ($doFixup -eq "y") {
    Write-Host "=== Normalizing line endings + permissions on the cluster ===" -ForegroundColor Cyan
    ssh -K $remote "cd $dstRoot && sed -i 's/\r`$//' run_pestpp_ies.slurm setup_worker.sh && chmod +x run_pestpp_ies.slurm setup_worker.sh pestpp-ies"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  WARNING: could not normalize scripts. Do it manually:" -ForegroundColor Red
        Write-Host "    ssh -K $remote"
        Write-Host "    cd $dstRoot && sed -i 's/\\r`$//' run_pestpp_ies.slurm setup_worker.sh && chmod +x run_pestpp_ies.slurm setup_worker.sh pestpp-ies"
    }
} else {
    Write-Host "Skipped fixup. After the transfer completes, run:" -ForegroundColor Yellow
    Write-Host "  ssh -K $remote"
    Write-Host "  cd $dstRoot && sed -i 's/\\r`$//' run_pestpp_ies.slurm setup_worker.sh && chmod +x run_pestpp_ies.slurm setup_worker.sh pestpp-ies"
}

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Green
Write-Host "Run directory: $dstRoot"
Write-Host ""
Write-Host "Next steps on the cluster:" -ForegroundColor Cyan
Write-Host "  ssh -K $remote"
Write-Host "  cd $dstRoot"
Write-Host "  conda activate <PYWATERSHED_ENV>"
Write-Host "  chmod +x pestpp-ies && ./pestpp-ies --version   # confirm shipped Linux binary"
Write-Host "  time python forward_run.py    # smoke-test one forward run"
Write-Host "  sbatch run_pestpp_ies.slurm   # submit the parallel run"
