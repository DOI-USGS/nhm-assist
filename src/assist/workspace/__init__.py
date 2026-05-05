"""Workspace bridge and service helpers for Pixi-driven workflows."""

from assist.workspace.bridge import (
    PROJECT_SUBDIRS,
    REPO_NOTEBOOK_DIRS,
    WORKFLOW_NAMES,
    ensure_workspace_root,
    get_project_dir,
    get_workflow_notebooks_dir,
    get_workspace_notebooks_dir,
    is_project_dir,
    list_projects,
    resolve_repo_root,
    resolve_workspace_root,
)
from assist.workspace.examples import resolve_example_source
from assist.workspace.service import (
    bootstrap_workspace,
    copy_example_project,
    create_project,
    get_projects,
    import_project,
)

__all__ = [
    "PROJECT_SUBDIRS",
    "REPO_NOTEBOOK_DIRS",
    "WORKFLOW_NAMES",
    "bootstrap_workspace",
    "copy_example_project",
    "create_project",
    "ensure_workspace_root",
    "get_projects",
    "get_project_dir",
    "get_workflow_notebooks_dir",
    "get_workspace_notebooks_dir",
    "import_project",
    "is_project_dir",
    "list_projects",
    "resolve_example_source",
    "resolve_repo_root",
    "resolve_workspace_root",
]
