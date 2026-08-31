import json
import shutil
from pathlib import Path

import yaml

from assist.workspace.bridge import (
    MODEL_SUBDIRS,
    PROJECT_MARKER_FILENAME,
    ensure_workspace_root,
    get_model_dir,
    get_project_active_model_config_path,
    get_project_config_dir,
    get_project_dir,
    is_model_dir,
    is_project_dir,
    list_models,
    list_projects,
    resolve_project_notebook_context,
    resolve_repo_root,
)
from assist.workspace.examples import resolve_example_source


NORMALIZED_SOURCE_DIR = "source_data"
SKIP_RUNTIME_COPY_NAMES = {"output", "notebook_output_files"}


def bootstrap_workspace(workspace_root: str | Path) -> dict[str, Path]:
    workspace = ensure_workspace_root(workspace_root)
    return {"workspace": workspace}


_PROJECT_MARKER_CONTENT = (
    "# nhm-assist project marker.\n"
    "# The CLI uses this file to detect the project root from a notebook's CWD.\n"
    "# Do not delete unless removing this project.\n"
    "schema_version: 1\n"
)


JUPYTEXT_CONFIG_FILENAME = "jupytext.toml"

_JUPYTEXT_CONFIG_CONTENT = (
    "# Pair every notebook under this project to a same-directory .py file.\n"
    "# jupytext walks up from each notebook to find this file, so it covers the\n"
    "# generated workflow notebooks and any sandbox notebook you create yourself.\n"
    'formats = "ipynb,py:percent"\n'
)


VSCODE_SETTINGS_FILENAME = ".vscode/settings.json"
VSCODE_EXTENSIONS_FILENAME = ".vscode/extensions.json"

JUPYTEXT_SYNC_EXTENSION_ID = "caenrigen.jupytext-sync"

# Pinned to the extension's own current defaults, rather than just the two
# event flags we care about: VS Code replaces object-typed settings wholesale
# per scope instead of merging keys, so a partial override here could
# silently blank out other keys a user set globally.
_VSCODE_SETTINGS_CONTENT = (
    json.dumps(
        {
            "jupytextSync.syncDocuments": {
                "onNotebookDocumentOpen": False,
                "onNotebookDocumentSave": True,
                "onNotebookDocumentClose": False,
                "onTextDocumentOpen": False,
                "onTextDocumentSave": True,
                "onTextDocumentClose": False,
            }
        },
        indent=2,
    )
    + "\n"
)

_VSCODE_EXTENSIONS_CONTENT = (
    json.dumps({"recommendations": [JUPYTEXT_SYNC_EXTENSION_ID]}, indent=2) + "\n"
)


def create_project(workspace_root: str | Path, project_name: str) -> dict[str, Path]:
    project_dir = get_project_dir(workspace_root, project_name)
    project_dir.mkdir(parents=True, exist_ok=True)

    marker_path = project_dir / PROJECT_MARKER_FILENAME
    if not marker_path.exists():
        marker_path.write_text(_PROJECT_MARKER_CONTENT, encoding="utf-8")

    paths = {"project": project_dir, "marker": marker_path}
    models_dir = project_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    paths["models"] = models_dir
    project_config_dir = get_project_config_dir(workspace_root, project_name)
    project_config_dir.mkdir(parents=True, exist_ok=True)
    paths["project_config"] = project_config_dir
    notebooks_dir = project_dir / "notebooks"
    notebooks_dir.mkdir(parents=True, exist_ok=True)
    paths["notebooks"] = notebooks_dir

    jupytext_config_path = project_dir / JUPYTEXT_CONFIG_FILENAME
    if not jupytext_config_path.exists():
        jupytext_config_path.write_text(_JUPYTEXT_CONFIG_CONTENT, encoding="utf-8")
    paths["jupytext_config"] = jupytext_config_path

    vscode_settings_path = project_dir / VSCODE_SETTINGS_FILENAME
    vscode_settings_path.parent.mkdir(parents=True, exist_ok=True)
    if not vscode_settings_path.exists():
        vscode_settings_path.write_text(_VSCODE_SETTINGS_CONTENT, encoding="utf-8")
    paths["vscode_settings"] = vscode_settings_path

    vscode_extensions_path = project_dir / VSCODE_EXTENSIONS_FILENAME
    if not vscode_extensions_path.exists():
        vscode_extensions_path.write_text(_VSCODE_EXTENSIONS_CONTENT, encoding="utf-8")
    paths["vscode_extensions"] = vscode_extensions_path

    return paths


def get_projects(workspace_root: str | Path) -> list[Path]:
    return list_projects(workspace_root)


def create_model(
    workspace_root: str | Path,
    project_name: str,
    model_name: str,
) -> dict[str, Path]:
    create_project(workspace_root, project_name)
    model_dir = get_model_dir(workspace_root, project_name, model_name)
    model_dir.mkdir(parents=True, exist_ok=True)

    paths = {"model": model_dir}
    for name in MODEL_SUBDIRS:
        path = model_dir / name
        path.mkdir(parents=True, exist_ok=True)
        paths[name] = path
    return paths


def get_models(workspace_root: str | Path, project_name: str) -> list[Path]:
    return list_models(workspace_root, project_name)


def set_active_model(
    workspace_root: str | Path,
    *,
    project_name: str,
    model_name: str,
) -> Path:
    project_dir = get_project_dir(workspace_root, project_name)
    if not is_project_dir(project_dir):
        raise FileNotFoundError(
            f"Project '{project_name}' not found at {project_dir}."
        )

    model_root = get_model_dir(workspace_root, project_name, model_name)
    if not model_root.is_dir():
        raise FileNotFoundError(
            f"Model '{model_name}' not found in project '{project_name}' at {model_root}."
        )

    config_dir = get_project_config_dir(workspace_root, project_name)
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = get_project_active_model_config_path(workspace_root, project_name)
    config_path.write_text(
        yaml.safe_dump({"active_model": model_name}, sort_keys=False),
        encoding="utf-8",
    )
    return config_path


def get_active_model_name(workspace_root: str | Path, project_name: str) -> str:
    project_root = get_project_dir(workspace_root, project_name)
    config_path = get_project_active_model_config_path(workspace_root, project_name)
    if not config_path.exists():
        raise FileNotFoundError(
            f"Missing active model config at {config_path}. "
            "Set an active model with `project-set-active-model` before running "
            "project notebooks."
        )

    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    active_model_name = data.get("active_model")
    if not active_model_name:
        raise ValueError(
            f"Active model config at {config_path} does not define `active_model`."
        )

    model_root = project_root / "models" / active_model_name
    if not model_root.is_dir():
        raise FileNotFoundError(
            f"Active model `{active_model_name}` from {config_path} does not exist "
            f"at {model_root}."
        )

    return active_model_name


def get_active_model_root(workspace_root: str | Path, project_name: str) -> Path:
    active_model_name = get_active_model_name(workspace_root, project_name)
    return get_model_dir(workspace_root, project_name, active_model_name)


def _copy_path(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def copy_example_model(
    workspace_root: str | Path,
    project_name: str,
    model_name: str,
    example_name: str,
) -> dict[str, Path]:
    existing_models = get_models(workspace_root, project_name)
    model_paths = create_model(workspace_root, project_name, model_name)
    source = resolve_example_source(example_name)
    copied_paths = _copy_source_into_model(source, model_paths)
    if not existing_models:
        set_active_model(
            workspace_root,
            project_name=project_name,
            model_name=model_name,
        )
    return copied_paths


def import_model(
    workspace_root: str | Path,
    project_name: str,
    model_name: str,
    source_dir: str | Path,
) -> dict[str, Path]:
    source = Path(source_dir).expanduser().resolve()
    if not source.is_dir():
        raise NotADirectoryError(source)

    model_paths = create_model(workspace_root, project_name, model_name)
    return _copy_source_into_model(source, model_paths)


def _copy_source_into_model(source: Path, model_paths: dict[str, Path]) -> dict[str, Path]:
    normalized_root = model_paths["inputs"] / NORMALIZED_SOURCE_DIR
    normalized_root.mkdir(parents=True, exist_ok=True)

    if is_model_dir(source):
        for source_subdir_name in ("config", "inputs"):
            source_subdir = source / source_subdir_name
            if not source_subdir.is_dir():
                continue
            dest_subdir = model_paths["model"] / source_subdir_name
            for child in source_subdir.iterdir():
                _copy_path(child, dest_subdir / child.name)

        source_outputs = source / "outputs"
        if source_outputs.is_dir():
            for child in source_outputs.iterdir():
                if child.name == "runtime":
                    continue
                _copy_path(child, model_paths["outputs"] / child.name)

        for child in source.iterdir():
            if child.name in {"config", "inputs", "outputs", "notebooks"}:
                continue
            _copy_path(child, normalized_root / child.name)
        return model_paths

    for child in source.iterdir():
        _copy_path(child, normalized_root / child.name)
    return model_paths


def _copy_model_source_into_runtime(source_model_dir: Path, runtime_model_dir: Path) -> None:
    runtime_model_dir.mkdir(parents=True, exist_ok=True)
    for child in source_model_dir.iterdir():
        if child.name in SKIP_RUNTIME_COPY_NAMES:
            continue
        _copy_path(child, runtime_model_dir / child.name)


def prepare_model_runtime(
    workspace_root: str | Path,
    *,
    project_name: str,
    model_name: str,
) -> dict[str, Path]:
    workspace = ensure_workspace_root(workspace_root)
    project_root = get_project_dir(workspace_root, project_name)
    model_root = get_model_dir(workspace_root, project_name, model_name)
    if not is_model_dir(model_root):
        raise NotADirectoryError(model_root)

    source_model_dir = model_root / "inputs" / NORMALIZED_SOURCE_DIR
    if not source_model_dir.is_dir():
        raise FileNotFoundError(source_model_dir)

    runtime_model_dir = model_root / "outputs" / "runtime"
    runtime_model_dir.parent.mkdir(parents=True, exist_ok=True)

    control_file = runtime_model_dir / "control.default.bandit"
    if not control_file.exists():
        _copy_model_source_into_runtime(source_model_dir, runtime_model_dir)

    return {
        "workspace_root": workspace,
        "project_root": project_root,
        "model_root": model_root,
        "source_model_dir": source_model_dir,
        "runtime_model_dir": runtime_model_dir,
        "config_root": model_root / "config",
    }


def resolve_nhm_runtime_paths(
    subdomain: str,
    *,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Path | None]:
    repo_root = resolve_repo_root(env=env)
    project_context = resolve_project_notebook_context(cwd=cwd, env=env)

    if project_context is None:
        return {
            "repo_root": repo_root,
            "config_root": repo_root,
            "workspace_root": None,
            "project_root": None,
            "model_root": None,
            "project_dir": None,
            "model_dir": repo_root / "domain_data" / subdomain,
        }

    active_model_name = get_active_model_name(
        project_context["workspace_root"], project_context["project_root"].name
    )
    runtime = prepare_model_runtime(
        project_context["workspace_root"],
        project_name=project_context["project_root"].name,
        model_name=active_model_name,
    )
    return {
        "repo_root": repo_root,
        "config_root": runtime["config_root"],
        "workspace_root": runtime["workspace_root"],
        "project_root": runtime["project_root"],
        "model_root": runtime["model_root"],
        "project_dir": runtime["project_root"],
        "model_dir": runtime["runtime_model_dir"],
        "active_model_name": active_model_name,
    }
