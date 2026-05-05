import shutil
from pathlib import Path

from assist.workspace.bridge import (
    PROJECT_SUBDIRS,
    WORKFLOW_NAMES,
    ensure_workspace_root,
    get_project_dir,
    get_workflow_notebooks_dir,
    get_workspace_notebooks_dir,
    is_project_dir,
    list_projects,
)
from assist.workspace.examples import resolve_example_source


NORMALIZED_SOURCE_DIR = "source_data"


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
