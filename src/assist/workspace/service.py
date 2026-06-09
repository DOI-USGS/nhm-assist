import shutil
from pathlib import Path

from assist.workspace.bridge import (
    PROJECT_SUBDIRS,
    WORKFLOW_NAMES,
    ensure_workspace_root,
    get_project_dir,
    resolve_repo_root,
    resolve_workspace_notebook_context,
    get_workflow_notebooks_dir,
    get_workspace_notebooks_dir,
    is_project_dir,
    list_projects,
)
from assist.workspace.examples import resolve_example_source


NORMALIZED_SOURCE_DIR = "source_data"
SKIP_RUNTIME_COPY_NAMES = {"output", "notebook_output_files"}


def bootstrap_workspace(workspace_root: str | Path) -> dict[str, Path | dict[str, Path]]:
    workspace = ensure_workspace_root(workspace_root)
    notebooks_dir = get_workspace_notebooks_dir(workspace)
    notebooks_dir.mkdir(parents=True, exist_ok=True)

    workflow_notebooks = {}
    for workflow in WORKFLOW_NAMES:
        workflow_dir = get_workflow_notebooks_dir(workflow, workspace)
        workflow_dir.mkdir(parents=True, exist_ok=True)
        workflow_notebooks[workflow] = workflow_dir

    return {
        "workspace": workspace,
        "notebooks": notebooks_dir,
        "workflow_notebooks": workflow_notebooks,
    }


def create_project(workspace_root: str | Path, project_name: str) -> dict[str, Path]:
    project_dir = get_project_dir(workspace_root, project_name)
    project_dir.mkdir(parents=True, exist_ok=True)

    paths = {"project": project_dir}
    for name in PROJECT_SUBDIRS:
        path = project_dir / name
        path.mkdir(parents=True, exist_ok=True)
        paths[name] = path
    return paths


def get_projects(workspace_root: str | Path) -> list[Path]:
    return list_projects(workspace_root)


def _copy_path(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _copy_structured_source(source: Path, project_paths: dict[str, Path]) -> dict[str, Path]:
    for name in PROJECT_SUBDIRS:
        _copy_path(source / name, project_paths[name])

    extras_destination = project_paths["inputs"] / NORMALIZED_SOURCE_DIR
    for child in source.iterdir():
        if child.name in PROJECT_SUBDIRS:
            continue
        _copy_path(child, extras_destination / child.name)

    return project_paths


def _copy_unstructured_source(source: Path, project_paths: dict[str, Path]) -> dict[str, Path]:
    normalized_root = project_paths["inputs"] / NORMALIZED_SOURCE_DIR
    normalized_root.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        _copy_path(child, normalized_root / child.name)
    return project_paths


def _copy_source_into_project(source: Path, project_paths: dict[str, Path]) -> dict[str, Path]:
    if is_project_dir(source):
        return _copy_structured_source(source, project_paths)
    return _copy_unstructured_source(source, project_paths)


def copy_example_project(
    workspace_root: str | Path,
    project_name: str,
    example_name: str,
) -> dict[str, Path]:
    project_paths = create_project(workspace_root, project_name)
    source = resolve_example_source(example_name)
    return _copy_source_into_project(source, project_paths)


def import_project(
    workspace_root: str | Path,
    project_name: str,
    source_dir: str | Path,
) -> dict[str, Path]:
    source = Path(source_dir).expanduser().resolve()
    if not source.is_dir():
        raise NotADirectoryError(source)

    project_paths = create_project(workspace_root, project_name)
    return _copy_source_into_project(source, project_paths)


def _resolve_runtime_project_dir(
    workspace_root: str | Path,
    subdomain: str,
    project_name: str | None = None,
) -> Path:
    workspace = ensure_workspace_root(workspace_root)

    if project_name is not None:
        project_dir = workspace / project_name
        if not is_project_dir(project_dir):
            raise NotADirectoryError(project_dir)
        return project_dir

    matching_project = workspace / subdomain
    if is_project_dir(matching_project):
        return matching_project

    projects = list_projects(workspace)
    if len(projects) == 1:
        return projects[0]

    raise ValueError(
        "could not determine workspace project automatically; "
        "use a project whose name matches the subdomain or keep only one project "
        "in the workspace"
    )


def _resolve_source_model_dir(project_dir: Path) -> Path:
    normalized_root = project_dir / "inputs" / NORMALIZED_SOURCE_DIR
    if normalized_root.is_dir():
        return normalized_root

    inputs_root = project_dir / "inputs"
    if inputs_root.is_dir() and any(inputs_root.iterdir()):
        return inputs_root

    raise FileNotFoundError(
        f"no source model data found under {normalized_root} or {inputs_root}"
    )


def _copy_model_source_into_runtime(source_model_dir: Path, runtime_model_dir: Path) -> None:
    runtime_model_dir.mkdir(parents=True, exist_ok=True)
    for child in source_model_dir.iterdir():
        if child.name in SKIP_RUNTIME_COPY_NAMES:
            continue
        _copy_path(child, runtime_model_dir / child.name)


def prepare_project_model_runtime(
    workspace_root: str | Path,
    subdomain: str,
    project_name: str | None = None,
) -> dict[str, Path]:
    project_dir = _resolve_runtime_project_dir(
        workspace_root, subdomain, project_name=project_name
    )
    source_model_dir = _resolve_source_model_dir(project_dir)
    runtime_model_dir = project_dir / "outputs" / subdomain
    runtime_model_dir.parent.mkdir(parents=True, exist_ok=True)

    control_file = runtime_model_dir / "control.default.bandit"
    if not control_file.exists():
        _copy_model_source_into_runtime(source_model_dir, runtime_model_dir)

    return {
        "workspace_root": ensure_workspace_root(workspace_root),
        "project_dir": project_dir,
        "source_model_dir": source_model_dir,
        "runtime_model_dir": runtime_model_dir,
        "config_root": ensure_workspace_root(workspace_root),
    }


def resolve_nhm_runtime_paths(
    subdomain: str,
    *,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    project_name: str | None = None,
) -> dict[str, Path | None]:
    repo_root = resolve_repo_root(env=env)
    workspace_context = resolve_workspace_notebook_context(cwd=cwd, env=env)

    if workspace_context is None:
        return {
            "repo_root": repo_root,
            "config_root": repo_root,
            "workspace_root": None,
            "project_dir": None,
            "model_dir": repo_root / "domain_data" / subdomain,
        }

    runtime = prepare_project_model_runtime(
        workspace_context["workspace_root"],
        subdomain,
        project_name=project_name,
    )
    return {
        "repo_root": repo_root,
        "config_root": runtime["config_root"],
        "workspace_root": runtime["workspace_root"],
        "project_dir": runtime["project_dir"],
        "model_dir": runtime["runtime_model_dir"],
    }
