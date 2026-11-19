# Running PEST++ IES on Hovenweep — Templates

Reusable templates for running a PEST++ IES calibration (pywatershed forward
model) on the Hovenweep HPC in parallel manager/worker mode. Copy these into a
run directory, edit the config, transfer, and submit.

> **Scope — this is an EXAMPLE remote workflow.** It targets USGS-specific
> resources (the Hovenweep HPC, Globus, DOI VPN + Kerberos), so parts of it only
> apply to USGS users. It is meant as a worked reference, not a
> one-size-fits-all: the same pattern — build a per-worker run dir, transfer
> inputs, submit a parallel manager/worker job, collect results — can be
> tailored to other HTC/HPC resources (a different Slurm cluster, AWS Batch, a
> local multi-core run). The USGS-specific pieces (Globus transfer, Kerberos,
> the `pestpp` module names) are the parts you would swap for your environment.
> Because it's optional and USGS-specific, its extra tooling (the Globus CLI)
> lives in the opt-in `remote-run` pixi environment, not the base install.

> **Direction:** these will evolve into user-modifiable templates driven by a
> setup notebook that guides a user through configuring and launching a
> calibration on a remote backend. For now they are hand-edited scripts.

- Cluster: `hw-login1.gs.doi.net` (edit account/partition for your center)
- Auth: Kerberos/GSSAPI (`ssh -K`) — must be on VPN
- pestpp module: `pestpp/5.2.19` (only `5.2.6` and `5.2.19` currently on Hovenweep)
- Python env: a conda env with pywatershed (for `forward_run.py`)

## Files

| File | Role |
|------|------|
| `hovenweep_config.env` | Central settings (user, account, paths, case, tasks, walltime) |
| `run_pestpp_ies.slurm` | SLURM batch script — launches manager + workers |
| `setup_worker.sh` | Builds one worker dir in scratch (copy small, symlink large) |
| `transfer_to_hpc_globus.ps1` | **Preferred** transfer via Globus CLI (DTN-backed, parallel, resumable) |
| `transfer_to_hpc.ps1` | Fallback transfer via `scp` (Kerberos/GSSAPI); fine for small/quick pushes |

The `hovenweep_pest_setup` notebook (`notebooks/pest/hovenweep_pest_setup.ipynb`) writes whichever transfer template you
pick (`TRANSFER_METHOD = "globus"` or `"scp"`) out as `transfer_to_hpc.ps1` in
your run dir, so the workflow steps below are identical either way.

Edit the `CONFIG` block in each script (or `hovenweep_config.env`) for your run.
Adapt the `COPY_FILES`/`SYMLINK_FILES` (in `setup_worker.sh`) and `$runFiles`
(in `transfer_to_hpc.ps1`) to your case name and file set.

## How the SLURM script works

`srun --multi-prog` launches different commands per rank in one allocation:
- **Rank 0 = manager** — `pestpp-ies <case>.pst /h :PORT` in the run dir; hands
  out realizations, collects results, writes all outputs here.
- **Ranks 1..N-1 = workers** — each connects to the manager and runs
  `python forward_run.py` per realization, from its own scratch directory.

`forward_run.py` writes `parameters.json`, `modelobs.dat`, and `output/` each
realization, so workers MUST be isolated. `setup_worker.sh` builds each worker a
scratch dir, copying small files and symlinking the large read-only NetCDFs.

## Transfer: Globus (preferred) vs scp

`scp` over a login node is discouraged for the ~0.5 GB of NetCDFs this run
ships — it's single-stream, doesn't resume, and hits the login node rather than
a data-transfer node (DTN). Globus uses the DTN-backed endpoints, parallelizes,
retries, resumes, and checksums. Use Globus for anything beyond a quick file.

**Globus one-time setup:**

1. Install the Globus CLI via the opt-in pixi environment. globus-cli is a
   command we invoke (not a Python import), so it lives in an opt-in
   `remote-run` feature/environment — NOT `[project.dependencies]`, and NOT in
   the `default` environment. Base nhm-assist and local runs need none of it.
   ```
   pixi run remote-setup          # pulls in the remote-run env + verifies globus
   # or: pixi install -e remote-run   then   pixi run -e remote-run globus ...
   ```
2. `globus login` (browser; USGS AD PIV+MFA).
3. Install **Globus Connect Personal** on your workstation so it's an endpoint;
   start it. Note its collection UUID.
4. Find the Hovenweep endpoint UUID: `globus endpoint search "Hovenweep"`.
   If it doesn't appear/connect, email hpc@usgs.gov to map your login shortname
   to your Globus identity.
5. Put both UUIDs in the notebook config (`GLOBUS_SRC_ENDPOINT`,
   `GLOBUS_DST_ENDPOINT`). The local path as seen through GCP is auto-derived
   (Windows `D:\...` → `/D/...`); override `GLOBUS_LOCAL_RUN_DIR` if your GCP
   mapping differs.

**What Globus can't do:** it moves data only — it can't `chmod +x` or strip
Windows CRLF line endings. `transfer_to_hpc_globus.ps1` therefore still makes one
`ssh -K` call after the transfer to normalize `run_pestpp_ies.slurm` /
`setup_worker.sh`. Wait for the transfer to COMPLETE (`globus task wait <id>`)
before that fixup runs.

## Workflow

1. **Transfer** (Windows PowerShell, on VPN):
   ```powershell
   # Globus (preferred): log in + confirm endpoints first
   globus login
   globus endpoint search "Hovenweep"
   .\transfer_to_hpc.ps1        # notebook writes the globus or scp variant here
   ```
2. **Prepare + smoke-test** on the cluster:
   ```bash
   ssh -K <user>@hw-login1.gs.doi.net
   cd <remote_run_dir>
   rm -f *.exe
   sed -i 's/\r$//' *.slurm *.sh
   chmod +x run_pestpp_ies.slurm setup_worker.sh
   mkdir -p logs
   module load pestpp/5.2.19 && conda activate <env>
   time python forward_run.py     # sizes walltime; expect output/*.nc + modelobs.dat
   ```
3. **Submit:** `sbatch run_pestpp_ies.slurm`  (prints a job ID)
4. **Monitor:**
   ```bash
   squeue -u <user>                 # PD=pending, R=running, CG=completing
   tail -f logs/manager.out         # PEST++ progress (Ctrl+C exits tail, not the job)
   cat scratch/<job_tag>_<jobid>/agent_1/worker.out
   ```
5. **Cancel** (e.g. on error — note a dead manager leaves workers holding the
   allocation until you cancel):
   ```bash
   scancel <jobid>
   squeue -u <user>
   ```
6. **Collect + clean up:** manager outputs (`<case>.*`) land in the run dir.
   ```bash
   rm -rf <scratch_base>/<job_tag>_<jobid>
   ```

## Gotchas

- **VPN + Kerberos** for all SSH/transfers. Test: `ssh -K <user>@... "echo ok"`.
  (Windows built-in `klist` shows the AD cache, not GSSAPI — the SSH test is real.)
- **`noptmax` in the `.pst`**: `-1` = prior Monte Carlo (validation run); positive
  = that many IES iterations. Change in the `.pst`, not the SLURM script.
- **Parameter bounds** must satisfy `parlbnd < parubnd` for every parameter or
  pestpp-ies aborts during control-file processing (`bounds are busted: 0 >= 0`).
  Percent-method bounds collapse to 0/0 for parameters whose start value is 0 —
  guard against this in the PEST setup (notebook 02b).
- **Windows line endings** in `.slurm`/`.sh` cause "bad interpreter" — always
  `sed -i 's/\r$//'` after transferring (the transfer script does this).
- **Sizing:** with N workers the ensemble runs in ceil(num_reals/(N-1)) waves;
  per-wave time ≈ slowest worker's forward-run time. Use the smoke-test time.
