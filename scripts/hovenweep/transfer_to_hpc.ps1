# =============================================================================
# transfer_to_hpc.ps1 — TEMPLATE: transfer a PEST++ IES run dir to Hovenweep.
#
# Run from Windows PowerShell while on VPN. Uses -K / GSSAPI (Kerberos) auth
# (test first: ssh -K <user>@hw-login1.gs.doi.net "echo ok").
#
# Edit the CONFIG block for your run. Ships only what the run needs; skips
# Windows .exe binaries and large stale local artifacts. Adapt $runFiles to
# your case name / file set (defaults match the CrookedRiver IES layout).
#
# See scripts/hovenweep/README_hovenweep_run.md for the full workflow.
# =============================================================================

$ErrorActionPreference = "Stop"

# --- CONFIG (edit per run) -------------------------------------------------
$hpcUser  = "<HPC_USER>"                  # your Hovenweep username
$center   = "<CENTER>"                    # your center allocation, e.g. wawsc
$remote   = "$hpcUser@hw-login1.gs.doi.net"
$workDir  = "/caldera/hovenweep/projects/usgs/water/$center/$hpcUser/<RUN_NAME>"
$localDir = "<LOCAL_RUN_DIR>"             # local path to your model's pestpp_ies/ dir
$caseName = "<CASE_NAME>"                 # <CASE_NAME>.pst

# Files required by the run (relative to $localDir). Edit for your case.
$runFiles = @(
    "$caseName.pst",
    "$caseName.pargp_data.csv",
    "$caseName.par_data.csv",
    "$caseName.obs_data.csv",
    "$caseName.tplfile_data.csv",
    "$caseName.insfile_data.csv",
    "forward_run.py",
    "parameters.json",
    "parameters.json.tpl",
    "modelobs.dat",
    "modelobs.dat.ins",
    "control.default.bandit",
    "loc.mat",
    "phi_factors.csv",
    "starting_par_vals.dat",
    "prcp.nc",
    "tmax.nc",
    "tmin.nc",
    "run_pestpp_ies.slurm",
    "run_pestpp_ies_1node.slurm",
    "setup_worker.sh",
    "pestpp-ies"
)

# Ship EVERY .jcb present in the local run dir, discovered at runtime rather
# than assumed from $caseName. PEST++ binary ensembles/matrices (the
# ies_observation_ensemble obs+noise file, parameter ensembles, restart jcbs)
# are frequently named with a DIFFERENT stem than the .pst case -- e.g. a case
# of "prior_mc_reweight_obs+noise_mod" whose obs ensemble is
# "prior_reweight_obs+noise_mod.jcb". The old hardcoded "$caseName.jcb" entry
# never matched those, so Test-Path skipped the file silently and the run died
# on the cluster with "error opening binary file ... .jcb". Enumerate by
# extension instead so the actual file ships no matter what it is called.
# (A literal '+' in a name such as "...obs+noise_mod.jcb" is safe here: '+' is
# not a PowerShell wildcard, so the Test-Path/scp loop below handles it as-is.)
$jcbFiles = @(Get-ChildItem -Path $localDir -Filter *.jcb -File -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty Name)
if ($jcbFiles.Count -gt 0) {
    Write-Host ("Found {0} .jcb file(s) to ship: {1}" -f $jcbFiles.Count, ($jcbFiles -join ", ")) -ForegroundColor Cyan
    $runFiles += $jcbFiles
} else {
    Write-Host "No .jcb files found in $localDir (ok if this run has no ensemble/matrix binaries)." -ForegroundColor DarkYellow
}

Write-Host "=== Step 1: Create remote directories ===" -ForegroundColor Cyan
ssh -K $remote "mkdir -p $workDir/logs $workDir/output $workDir/observation_data $workDir/ancillary"
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: SSH failed. Check VPN and Kerberos (ssh -K test)." -ForegroundColor Red; exit 1 }

Write-Host "=== Step 2: Transfer run files ===" -ForegroundColor Cyan
foreach ($f in $runFiles) {
    $src = "$localDir/$f"
    if (-not (Test-Path $src)) { Write-Host "  SKIP (missing): $f" -ForegroundColor DarkYellow; continue }
    Write-Host "  -> $f" -ForegroundColor Yellow
    scp -o GSSAPIAuthentication=yes $src "${remote}:${workDir}/"
    if ($LASTEXITCODE -ne 0) { Write-Host "  ERROR transferring $f" -ForegroundColor Red }
}

Write-Host "=== Step 3: Transfer observation_data/ (read-only NetCDFs) ===" -ForegroundColor Cyan
scp -o GSSAPIAuthentication=yes "$localDir/observation_data/*" "${remote}:${workDir}/observation_data/"
if ($LASTEXITCODE -ne 0) { Write-Host "  ERROR transferring observation_data" -ForegroundColor Red }

Write-Host "=== Step 4: Transfer ancillary/ (read-only CSVs) ===" -ForegroundColor Cyan
scp -o GSSAPIAuthentication=yes "$localDir/ancillary/*" "${remote}:${workDir}/ancillary/"
if ($LASTEXITCODE -ne 0) { Write-Host "  ERROR transferring ancillary" -ForegroundColor Red }

Write-Host "=== Step 5: Normalize line endings + permissions on the cluster ===" -ForegroundColor Cyan
ssh -K $remote "cd $workDir && sed -i 's/\r`$//' run_pestpp_ies.slurm run_pestpp_ies_1node.slurm setup_worker.sh && chmod +x run_pestpp_ies.slurm run_pestpp_ies_1node.slurm setup_worker.sh pestpp-ies"
if ($LASTEXITCODE -ne 0) { Write-Host "  WARNING: could not normalize scripts (do it manually)." -ForegroundColor Red }

Write-Host ""
Write-Host "=== Transfer complete ===" -ForegroundColor Green
Write-Host "Run directory: $workDir"
Write-Host ""
Write-Host "Next steps on the cluster:" -ForegroundColor Cyan
Write-Host "  ssh -K $remote"
Write-Host "  cd $workDir"
Write-Host "  conda activate <PYWATERSHED_ENV>"
Write-Host "  chmod +x pestpp-ies && ./pestpp-ies --version   # confirm shipped Linux binary"
Write-Host "  time python forward_run.py    # smoke-test one forward run"
Write-Host "  sbatch run_pestpp_ies.slurm   # submit the parallel run"
