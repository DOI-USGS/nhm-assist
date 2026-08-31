import os
from pathlib import Path
from typing import Mapping


WORKFLOW_NAMES = ("nhm", "nhf", "pest")
MODEL_SUBDIRS = ("config", "inputs", "outputs")
PROJECT_MARKER_FILENAME = ".nhm-assist-project"


def resolve_repo_root(env: Mapping[str, str] | None = None) -> Path:
    env_map = os.environ if env is None else env
    pixi_root = env_map.get("PIXI_PROJECT_ROOT")
    if pixi_root:
        return Path(pixi_root).expanduser().resolve()
    return Path(__file__).resolve().parents[3]


def resolve_workspace_root(
    workspace_root: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> Path | None:
    if workspace_root is not None:
        return Path(workspace_root).expanduser().resolve()

    env_map = os.environ if env is None else env
    env_value = env_map.get("NHM_ASSIST_WORKSPACE_ROOT")
    if env_value:
        return Path(env_value).expanduser().resolve()

    return None


def ensure_workspace_root(
    workspace_root: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    resolved = resolve_workspace_root(workspace_root, env=env)
    if resolved is None:
        raise ValueError("workspace root is required for this command")

    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def get_project_dir(
    workspace_root: str | Path | None,
    project_name: str,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    return ensure_workspace_root(workspace_root, env=env) / project_name


def get_project_models_dir(
    workspace_root: str | Path | None,
    project_name: str,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    return get_project_dir(workspace_root, project_name, env=env) / "models"


def get_project_notebooks_dir(
    workspace_root: str | Path | None,
    project_name: str,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    return get_project_dir(workspace_root, project_name, env=env) / "notebooks"


def get_project_workflow_notebooks_dir(
    workflow: str,
    workspace_root: str | Path | None,
    project_name: str,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    if workflow not in WORKFLOW_NAMES:
        raise ValueError(f"unsupported workflow: {workflow}")
    return get_project_notebooks_dir(
        workspace_root, project_name, env=env
    ) / workflow


def get_project_config_dir(
    workspace_root: str | Path | None,
    project_name: str,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    return get_project_dir(workspace_root, project_name, env=env) / "project_config"


def get_project_active_model_config_path(
    workspace_root: str | Path | None,
    project_name: str,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    return get_project_config_dir(
        workspace_root, project_name, env=env
    ) / "active_model.yaml"


def get_model_dir(
    workspace_root: str | Path | None,
    project_name: str,
    model_name: str,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    return get_project_models_dir(workspace_root, project_name, env=env) / model_name


def is_project_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    return (path / PROJECT_MARKER_FILENAME).is_file() or (path / "models").is_dir()


def is_project_dir_by_marker(path: Path) -> bool:
    return path.is_dir() and (path / PROJECT_MARKER_FILENAME).is_file()


def is_model_dir(path: Path) -> bool:
    return path.is_dir() and all((path / name).is_dir() for name in MODEL_SUBDIRS)


def list_projects(
    workspace_root: str | Path | None,
    *,
    env: Mapping[str, str] | None = None,
) -> list[Path]:
    workspace = ensure_workspace_root(workspace_root, env=env)
    return sorted([child for child in workspace.iterdir() if is_project_dir(child)])


def list_models(
    workspace_root: str | Path | None,
    project_name: str,
    *,
    env: Mapping[str, str] | None = None,
) -> list[Path]:
    models_root = get_project_models_dir(workspace_root, project_name, env=env)
    if not models_root.exists():
        return []
    return sorted([child for child in models_root.iterdir() if is_model_dir(child)])


def _build_marker_context(
    project_root: Path,
    current: Path,
) -> dict[str, Path | str | None]:
    workspace_root = project_root.parent.resolve()
    workflow: str | None = None
    workflow_dir: Path | None = None
    notebooks_dir: Path | None = None

    try:
        relative_parts = current.relative_to(project_root).parts
    except ValueError:
        relative_parts = ()

    for idx, part in enumerate(relative_parts):
        if part in WORKFLOW_NAMES:
            workflow = part
            workflow_dir = project_root.joinpath(*relative_parts[: idx + 1])
            notebooks_dir = workflow_dir.parent
            break

    return {
        "workspace_root": workspace_root,
        "project_root": project_root,
        "project_config_root": project_root / "project_config",
        "workflow": workflow,
        "notebooks_dir": notebooks_dir,
        "workflow_dir": workflow_dir,
    }


def _resolve_by_legacy_name_heuristic(
    current: Path,
) -> dict[str, Path | str] | None:
    for candidate in (current, *current.parents):
        if candidate.name not in WORKFLOW_NAMES:
            continue
        notebooks_dir = candidate.parent
        if notebooks_dir.name != "notebooks":
            continue

        project_root = notebooks_dir.parent.resolve()
        if not is_project_dir(project_root):
            continue

        workspace_root = project_root.parent.resolve()
        return {
            "workspace_root": workspace_root,
            "project_root": project_root,
            "project_config_root": project_root / "project_config",
            "workflow": candidate.name,
            "notebooks_dir": notebooks_dir.resolve(),
            "workflow_dir": candidate.resolve(),
        }
    return None


def resolve_project_notebook_context(
    cwd: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, Path | str | None] | None:
    del env  # reserved for future runtime overrides
    current = Path.cwd() if cwd is None else Path(cwd)
    current = current.expanduser().resolve()

    for candidate in (current, *current.parents):
        if is_project_dir_by_marker(candidate):
            return _build_marker_context(candidate, current)

    return _resolve_by_legacy_name_heuristic(current)
