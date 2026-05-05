import os
from pathlib import Path
from typing import Mapping


WORKFLOW_NAMES = ("nhm", "nhf", "pest")
REPO_NOTEBOOK_DIRS = {
    "nhm": Path("notebooks"),
    "nhf": Path("nhf_assist") / "notebooks",
    "pest": Path("pestpp_ies_calibration") / "notebooks",
}
PROJECT_SUBDIRS = ("config", "inputs", "outputs")


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


def get_workspace_notebooks_dir(
    workspace_root: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    return ensure_workspace_root(workspace_root, env=env) / "notebooks"


def get_workflow_notebooks_dir(
    workflow: str,
    workspace_root: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    if workflow not in WORKFLOW_NAMES:
        raise ValueError(f"unsupported workflow: {workflow}")

    resolved_workspace = resolve_workspace_root(workspace_root, env=env)
    if resolved_workspace is None:
        return resolve_repo_root(env=env) / REPO_NOTEBOOK_DIRS[workflow]

    return resolved_workspace / "notebooks" / workflow


def get_project_dir(
    workspace_root: str | Path | None,
    project_name: str,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    return ensure_workspace_root(workspace_root, env=env) / project_name


def is_project_dir(path: Path) -> bool:
    return path.is_dir() and all((path / name).is_dir() for name in PROJECT_SUBDIRS)


def list_projects(
    workspace_root: str | Path | None,
    *,
    env: Mapping[str, str] | None = None,
) -> list[Path]:
    workspace = ensure_workspace_root(workspace_root, env=env)
    return sorted(
        [
            child
            for child in workspace.iterdir()
            if child.name != "notebooks" and is_project_dir(child)
        ]
    )
