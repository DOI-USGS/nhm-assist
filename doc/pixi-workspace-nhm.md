# NHM Pixi Workspace Guide

This branch adds a Pixi-driven workspace flow for the NHM notebooks. The goal is to let a user keep notebook execution, generated config, model outputs, and exported HTML products in a personal workspace instead of writing back into the repository checkout.

## What the workspace is

The repository stays the source of truth for:

- Python source code
- notebook templates
- shared helper modules
- shared `data_dependencies`
- the Pixi environment definition

The workspace is a user-owned directory where generated notebooks and project data live.

A typical workspace looks like this:

```text
<workspace>/
  notebooks/
    nhm/
      0_workspace_setup.ipynb
      1_create_streamflow_observations.ipynb
      ...
  Walla_Walla/
    config/
    inputs/
      source_data/
        control.default.bandit
        myparam.param
        cbh.nc
        GIS/
        ...
    outputs/
      Walla_Walla/
        control.default.bandit
        myparam.param
        cbh.nc
        GIS/
        output/
        notebook_output_files/
```

## How the layout works

Each project inside the workspace has three top-level folders:

- `config/`: reserved for project-specific config files
- `inputs/`: source model data copied or imported into the workspace
- `outputs/`: runtime model copy plus notebook/model outputs

The runtime behavior is intentionally split:

1. Source model files are stored under:

   ```text
   <project>/inputs/source_data/
   ```

2. When notebook `0_workspace_setup.ipynb` runs in workspace mode, the notebooks prepare a runtime model directory at:

   ```text
   <project>/outputs/<subdomain>/
   ```

3. The runtime copy is what notebooks 1-6 use as `model_dir`.

4. Generated files such as `default_gages.csv`, `NWISgages.csv`, `output/*.nc`, and `notebook_output_files/*` are written under the runtime output area, not back into `inputs/source_data`.

This keeps the imported source model as intact as possible while still letting the notebooks write the files they expect.

## What notebook runtime detection does

The NHM templates on this branch now separate:

- `repo_root`: the repository checkout, used for code and shared `data_dependencies`
- `config_root`: the place where `subdomain_config.yaml` is written and read
- `model_dir`: the runtime model folder used by the notebooks

When a notebook is launched from a workspace path like:

```text
<workspace>/notebooks/nhm/
```

the notebook auto-detects workspace mode and does the following:

- writes `subdomain_config.yaml` to the workspace root
- reads and writes model files from `<project>/outputs/<subdomain>`
- still uses repository assets from `<repo>/data_dependencies`

When the same notebook is launched from the repository `notebooks/` directory, it stays in legacy repo-local mode and uses:

```text
<repo>/domain_data/<subdomain>
```

## Pixi commands

Run these commands from the repository root.

### 1. Install the Pixi environment

```bash
pixi install
```

### 2. Choose a workspace folder

```bash
WORKSPACE=~/nhm-workspace
```

You can use any writable location.

### 3. Create the workspace skeleton

```bash
pixi run workspace-init "$WORKSPACE"
```

This creates:

```text
<workspace>/notebooks/
<workspace>/notebooks/nhm/
<workspace>/notebooks/nhf/
<workspace>/notebooks/pest/
```

### 4a. Copy a repository example into a workspace project

For the NHM example on this branch:

```bash
pixi run project-copy-example "$WORKSPACE" Walla_Walla Walla_Walla
```

This creates:

```text
<workspace>/Walla_Walla/config
<workspace>/Walla_Walla/inputs
<workspace>/Walla_Walla/outputs
```

and copies the example model into `inputs/source_data/`.

### 4b. Import an existing folder instead of a repository example

If a collaborator already has a model folder somewhere else:

```bash
pixi run project-import "$WORKSPACE" My_Project /absolute/path/to/model_folder
```

If the imported folder is already in the workspace project structure, those subfolders are copied directly. If it is just a raw model directory, it is normalized into:

```text
<workspace>/My_Project/inputs/source_data/
```

### 5. Generate workspace notebooks

```bash
pixi run notebooks-workspace "$WORKSPACE" nhm
```

This writes generated NHM notebooks to:

```text
<workspace>/notebooks/nhm/
```

The repository notebook templates are not executed directly in the workspace flow; generated notebook copies are.

### 6. Launch Jupyter against the workspace notebooks

```bash
pixi run jupyter lab "$WORKSPACE/notebooks/nhm"
```

Open the notebooks from the workspace location, not from the repository `notebooks/` folder.

## Notebook order

For a full NHM run, use the notebooks in order:

1. `0_workspace_setup.ipynb`
2. `1_create_streamflow_observations.ipynb`
3. `2_model_hydrofabric_visualization.ipynb`
4. `3_model_parameter_visualization.ipynb`
5. `4_run_model_using_pywatershed.ipynb`
6. `5_hru_output_visualization_new.ipynb`
7. `6_streamflow_output_visualization_new.ipynb`

In practice:

- notebook 0 prepares runtime paths and writes `subdomain_config.yaml`
- notebook 1 creates observation and gage support files
- notebook 4 produces model output files needed by notebooks 5 and 6

If notebook 5 or 6 is run before notebook 4, missing output-file errors are expected.

## Where outputs go

In workspace mode, notebook and model outputs are written under:

```text
<workspace>/<project>/outputs/<subdomain>/
```

Important locations:

- model runtime directory:

  ```text
  <workspace>/<project>/outputs/<subdomain>/
  ```

- model output netCDF files:

  ```text
  <workspace>/<project>/outputs/<subdomain>/output/
  ```

- notebook-exported HTML maps and plots:

  ```text
  <workspace>/<project>/outputs/<subdomain>/notebook_output_files/html_maps/
  <workspace>/<project>/outputs/<subdomain>/notebook_output_files/html_plots/
  ```

## Common mistakes

### Opening the wrong notebook copy

If you generated workspace notebooks, open:

```text
<workspace>/notebooks/nhm/
```

not the repository `notebooks/` directory.

### Running Jupyter from the wrong environment

If you are testing the Pixi workflow, prefer:

```bash
pixi run jupyter lab "$WORKSPACE/notebooks/nhm"
```

so the kernel and imports match the Pixi environment used to generate the notebooks.

### Expecting imported source data to receive outputs

Outputs are intentionally written to the runtime copy under `outputs/<subdomain>`, not to `inputs/source_data`.

### Keeping multiple projects with names unrelated to the selected subdomain

Workspace runtime auto-detection prefers:

1. a project whose name matches the selected subdomain
2. otherwise, the only project in the workspace

If a workspace contains several projects, use project names that match the intended subdomain to avoid ambiguity.

## Quick start

```bash
pixi install
WORKSPACE=~/nhm-workspace
pixi run workspace-init "$WORKSPACE"
pixi run project-copy-example "$WORKSPACE" Walla_Walla Walla_Walla
pixi run notebooks-workspace "$WORKSPACE" nhm
pixi run jupyter lab "$WORKSPACE/notebooks/nhm"
```

Then run notebook 0 first.
