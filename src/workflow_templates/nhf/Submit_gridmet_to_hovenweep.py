# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.3
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Submit GridMET Climate Drivers to Hovenweep HPC
#
# This notebook generates SLURM job files and provides copy-paste commands
# to transfer and submit jobs on Hovenweep.
#
# **Prerequisites:**
# - Hovenweep account with SSH access (`ssh user@hw-login1.gs.doi.net`)
# - VPN connection
# - Child model geopackages generated locally
# - miniforge3 installed on Hovenweep (`/home/<user>/miniforge3`)
#
# **Workflow:**
# 1. Configure and generate SLURM files
# 2. Copy commands to transfer files to Hovenweep
# 3. Copy commands to set up env and submit jobs
# 4. Copy commands to retrieve results

# %% [markdown]
# ---
# ## 1. Configuration
#
# Edit the `.env.hovenweep` file in `nhf_assist/slurm/` with your credentials.
#
# **SSH to Hovenweep:** `ssh <username>@hw-login1.gs.doi.net`
# - Requires VPN connection
# - Two login nodes: `hw-login1` or `hw-login2`
# - If using Kerberos auth, add `-K` flag: `ssh -K <username>@hw-login1.gs.doi.net`
# - Run jobs from `/caldera/projects/`, NOT `$HOME`

# %%
import os
import pathlib as pl
import shutil

# Find nhf_assist root
root_folder = "nhf_assist"
root_dir = pl.Path(os.getcwd().rsplit(root_folder, 1)[0] + root_folder)
slurm_dir = root_dir / "slurm"

# Create .env.hovenweep from template if needed
env_file = slurm_dir / ".env.hovenweep"
template_file = slurm_dir / ".env.hovenweep.template"

if not env_file.exists():
    shutil.copy(template_file, env_file)
    print(f"Created {env_file} — EDIT THIS FILE before continuing.")
else:
    print(f"Using: {env_file}")

# Load config
hpc = {}
with open(env_file) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            hpc[key.strip()] = val.strip()

print("\nHPC Config:")
for k, v in hpc.items():
    print(f"  {k} = {v}")

# %% [markdown]
# ---
# ## 2. Select child models

# %%
child_models = [
    "MiddleWillamette",
    "NorthCoast_MidCoastA",
    "OwyheeRiver",
    "PowderRiver",
    "SandyRiver",
    "SouthCoastB_LowerRogue",
    "UmatillaRiver",
    "UpperRogue",
    "UpperUmpqua",
    "UpperWillamette",
]

# Check local geopackages
ready = []
for m in child_models:
    gpkg = root_dir / "domain_data" / m / "GIS" / "model_layers.gpkg"
    if gpkg.exists():
        ready.append(m)
        print(f"  + {m}")
    else:
        print(f"  - {m} (MISSING)")

print(f"\nReady: {len(ready)} / {len(child_models)}")

# %% [markdown]
# ---
# ## 3. Generate SLURM files
#
# Creates all files needed on Hovenweep in `nhf_assist/slurm/`.

# %%
# --- SLURM array job script ---
array_max = len(ready) - 1
models_bash = "\n".join([f'    "{m}"' for m in ready])

slurm_script = f"""#!/bin/bash
#SBATCH --job-name=gridmet_drivers
#SBATCH --account={hpc['HPC_ACCOUNT']}
#SBATCH --partition={hpc['PARTITION']}
#SBATCH --array=0-{array_max}
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=12:00:00
#SBATCH --output=logs/gridmet_%A_%a.out
#SBATCH --error=logs/gridmet_%A_%a.err

source "{hpc['CONDA_DIR']}/etc/profile.d/conda.sh"
conda activate {hpc['ENV_NAME']}
cd "{hpc['HPC_WORK_DIR']}" || exit 1

# Use system CA bundle (includes DOI certs) instead of conda's certifi
export SSL_CERT_FILE=/etc/pki/tls/certs/ca-bundle.crt
export REQUESTS_CA_BUNDLE=/etc/pki/tls/certs/ca-bundle.crt

CHILD_MODELS=(
{models_bash}
)

MODEL_NAME="${{CHILD_MODELS[$SLURM_ARRAY_TASK_ID]}}"
echo "Processing: $MODEL_NAME on $(hostname) at $(date)"
python run_gridmet_single.py "$MODEL_NAME"
echo "Done: $MODEL_NAME at $(date)"
"""

(slurm_dir / "gridmet_array_job.sh").write_text(slurm_script.replace('\r\n', '\n'), newline='\n')
print(f"Generated: gridmet_array_job.sh ({len(ready)} models, array 0-{array_max})")

# --- Environment YAML ---
env_yml = f"""name: {hpc['ENV_NAME']}
channels:
  - conda-forge
dependencies:
  - python>=3.10
  - pandas
  - numpy
  - xarray
  - geopandas
  - rioxarray
  - netcdf4
  - dask
  - distributed
  - requests
  - tqdm
  - shapely
  - fiona
  - pyproj
  - pyyaml
  - pip
  - pip:
    - gdptools
"""
(slurm_dir / "environment_hpc.yml").write_text(env_yml.replace('\r\n', '\n'), newline='\n')
print("Generated: environment_hpc.yml")
print("\nAll files ready in:", slurm_dir)

# %% [markdown]
# ---
# ## 4. Transfer files to Hovenweep
#
# This cell generates a PowerShell script (`transfer_to_hpc.ps1`) that handles
# all file transfers in one shot. Run it in your local terminal.
#
# **Requires:** VPN connection + SSH access to Hovenweep.

# %%
remote = f"{hpc['HPC_USER']}@{hpc['HPC_HOST']}"
work_dir = hpc['HPC_WORK_DIR']
local_slurm = str(slurm_dir).replace("\\", "/")
local_domain = str(root_dir / "domain_data").replace("\\", "/")

# Build PowerShell script content
ps_lines = [
    '# transfer_to_hpc.ps1',
    '# Generated by Submit_gridmet_to_hovenweep.ipynb',
    '# Run this from PowerShell while connected to VPN',
    '# Uses -K (Kerberos/GSSAPI) for SSH authentication',
    '',
    '$ErrorActionPreference = "Stop"',
    '',
    f'$remote = "{remote}"',
    f'$workDir = "{work_dir}"',
    '',
    'Write-Host "=== Step 1: Create remote directories ===" -ForegroundColor Cyan',
    f'ssh -K $remote "mkdir -p $workDir/logs $workDir/domain_data"',
    'if ($LASTEXITCODE -ne 0) {{ Write-Host "ERROR: SSH failed. Check VPN and credentials." -ForegroundColor Red; exit 1 }}',
    '',
    'Write-Host "=== Step 2: Transfer scripts ===" -ForegroundColor Cyan',
    f'scp -o GSSAPIAuthentication=yes {local_slurm}/gridmet_array_job.sh {local_slurm}/run_gridmet_single.py {local_slurm}/gridmet_core.py {local_slurm}/environment_hpc.yml {local_slurm}/setup_hpc_env.sh ${{remote}}:${{workDir}}/',
    'if ($LASTEXITCODE -ne 0) {{ Write-Host "ERROR: Script transfer failed." -ForegroundColor Red; exit 1 }}',
    '',
    'Write-Host "=== Step 3: Transfer geopackages ===" -ForegroundColor Cyan',
]

for i, m in enumerate(ready):
    local_gpkg = str(root_dir / "domain_data" / m / "GIS" / "model_layers.gpkg").replace("\\", "/")
    ps_lines.append(f'Write-Host "  [{i+1}/{len(ready)}] {m}" -ForegroundColor Yellow')
    ps_lines.append(f'ssh -K $remote "mkdir -p $workDir/domain_data/{m}/GIS"')
    ps_lines.append(f'scp -o GSSAPIAuthentication=yes {local_gpkg} ${{remote}}:${{workDir}}/domain_data/{m}/GIS/')
    ps_lines.append(f'if ($LASTEXITCODE -ne 0) {{ Write-Host "WARNING: Failed to transfer {m}" -ForegroundColor Red }}')
    ps_lines.append('')

ps_lines.append('Write-Host ""')
ps_lines.append('Write-Host "=== Transfer complete! ===" -ForegroundColor Green')
ps_lines.append(f'Write-Host "Files are at: $workDir on {hpc["HPC_HOST"]}"')
ps_lines.append('Write-Host "Next: SSH in and run setup_hpc_env.sh, then sbatch gridmet_array_job.sh"')

# Write the script
ps_script = "\n".join(ps_lines)
ps_path = slurm_dir / "transfer_to_hpc.ps1"
ps_path.write_text(ps_script)

print(f"Generated: {ps_path}")
print(f"\nRun in PowerShell:")
print(f"  powershell -ExecutionPolicy Bypass -File \"{ps_path}\"")
print(f"\n  -- or just right-click > 'Run with PowerShell' --")

# %% [markdown]
# ---
# ## 5. Set up environment & submit (on Hovenweep)
#
# SSH into Hovenweep and run these commands.

# %%
print("="*70)
print("RUN THESE ON HOVENWEEP (after SSH'ing in):")
print("="*70)

print(f"\n# SSH in:")
print(f"ssh -K {remote}")

print(f"\n# Navigate to work directory:")
print(f"cd {work_dir}")

print(f"\n# One-time: Create conda environment (takes ~5 min):")
print(f"bash setup_hpc_env.sh")

print(f"\n# Submit the array job:")
print(f"sbatch gridmet_array_job.sh")

print(f"\n# Monitor:")
print(f"squeue -u {hpc['HPC_USER']}")
print(f"tail -f logs/gridmet_*.out")

print(f"\n# Cancel if needed:")
print(f"scancel --user={hpc['HPC_USER']}")

# %% [markdown]
# ---
# ## 6. Retrieve results
#
# Once jobs complete, run the generated `retrieve_from_hpc.ps1` to pull
# forcing files back to your local machine.

# %%
# Build retrieval PowerShell script
ret_lines = [
    '# retrieve_from_hpc.ps1',
    '# Generated by Submit_gridmet_to_hovenweep.ipynb',
    '# Run this from PowerShell after SLURM jobs complete',
    '# Uses GSSAPI (Kerberos) for SSH authentication',
    '',
    '$ErrorActionPreference = "Stop"',
    '',
    f'$remote = "{remote}"',
    f'$workDir = "{work_dir}"',
    '',
    'Write-Host "=== Retrieving gridMET results from Hovenweep ===" -ForegroundColor Cyan',
    '',
]

for i, m in enumerate(ready):
    local_dir = str(root_dir / "domain_data" / m).replace("\\", "/")
    ret_lines.append(f'Write-Host "  [{i+1}/{len(ready)}] {m}" -ForegroundColor Yellow')
    ret_lines.append(f'scp -o GSSAPIAuthentication=yes ${{remote}}:${{workDir}}/domain_data/{m}/*.nc {local_dir}/')
    ret_lines.append(f'if ($LASTEXITCODE -ne 0) {{ Write-Host "WARNING: No .nc files for {m} (may still be running)" -ForegroundColor Red }}')
    ret_lines.append('')

ret_lines.append('Write-Host ""')
ret_lines.append('Write-Host "=== Retrieval complete! ===" -ForegroundColor Green')
ret_lines.append('Write-Host "You can now run notebook 4 (pywatershed) locally for each model."')

ret_script = "\n".join(ret_lines)
ret_path = slurm_dir / "retrieve_from_hpc.ps1"
ret_path.write_text(ret_script)

print(f"Generated: {ret_path}")
print(f"\nRun in PowerShell (after jobs finish):")
print(f"  powershell -ExecutionPolicy Bypass -File \"{ret_path}\"")
