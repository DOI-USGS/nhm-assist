from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values, set_key

from assist.workspace import bridge, service
from assist.workspace.examples import EXAMPLE_SOURCE_DIR_NAMES
from workflow_templates import make_notebooks as notebook_builder


@dataclass
class SetupState:
    repo_root: Path
    workspace_root: Path | None = None
    current_project: str | None = None


def get_repo_dotenv_path(repo_root: Path) -> Path:
    return repo_root / ".env"


def load_workspace_root_from_dotenv(repo_root: Path) -> Path | None:
    dotenv_path = get_repo_dotenv_path(repo_root)
    if not dotenv_path.exists():
        return None

    values = dotenv_values(dotenv_path)
    value = values.get("NHM_ASSIST_WORKSPACE_ROOT")
    if not value:
        return None

    return Path(value).expanduser().resolve()


def save_workspace_root_to_dotenv(
    repo_root: Path,
    workspace_root: str | Path,
) -> Path:
    dotenv_path = get_repo_dotenv_path(repo_root)
    resolved = Path(workspace_root).expanduser().resolve()
    if not dotenv_path.exists():
        dotenv_path.touch()

    set_key(
        str(dotenv_path),
        "NHM_ASSIST_WORKSPACE_ROOT",
        str(resolved),
    )
    return dotenv_path


def prompt_required_text(prompt: str, *, input_func=input) -> str:
    while True:
        value = input_func(f"{prompt} ").strip()
        if value:
            return value


def prompt_yes_no(prompt: str, *, default: bool = True, input_func=input) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        raw = input_func(f"{prompt} {suffix} ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False


def prompt_menu_choice(max_choice: int, *, input_func=input, print_func=print) -> int:
    while True:
        raw = input_func(f"Select menu option number [0-{max_choice}]: ").strip()
        try:
            choice = int(raw)
        except ValueError:
            print_func("Please enter a menu number.")
            continue

        if 0 <= choice <= max_choice:
            return choice
        print_func(f"Please enter a menu number between 0 and {max_choice}.")


def get_active_model_name_for_state(state: SetupState) -> str | None:
    if state.workspace_root is None or state.current_project is None:
        return None

    try:
        return service.get_active_model_name(state.workspace_root, state.current_project)
    except (FileNotFoundError, ValueError):
        return None


def list_available_example_names(repo_root: Path) -> list[str]:
    names: set[str] = set()
    for dir_name in EXAMPLE_SOURCE_DIR_NAMES:
        root = repo_root / dir_name
        if not root.is_dir():
            continue
        for child in root.iterdir():
            if child.is_dir():
                names.add(child.name)
    return sorted(names)


def prompt_workspace_root(
    repo_root: Path,
    *,
    print_func=print,
    input_func=input,
) -> Path:
    while True:
        raw_path = prompt_required_text(
            "Type workspace root path:",
            input_func=input_func,
        )
        workspace_root = Path(raw_path).expanduser().resolve()

        if workspace_root.exists() and not workspace_root.is_dir():
            print_func(f"Path is not a directory: {workspace_root}")
            continue

        if not workspace_root.exists():
            create_dir = prompt_yes_no(
                "Create this folder?",
                input_func=input_func,
            )
            if not create_dir:
                continue
            workspace_root.mkdir(parents=True, exist_ok=True)

        save_workspace_root_to_dotenv(repo_root, workspace_root)
        return workspace_root


def action_set_workspace_root(
    state: SetupState,
    *,
    print_func=print,
    input_func=input,
) -> Path:
    workspace_root = prompt_workspace_root(
        state.repo_root,
        print_func=print_func,
        input_func=input_func,
    )
    state.workspace_root = workspace_root
    print_func(f"Workspace root set to {workspace_root}")
    return workspace_root


def require_workspace_root(state: SetupState) -> Path:
    if state.workspace_root is None:
        raise ValueError("Workspace root is not configured.")
    return state.workspace_root


def require_current_project(state: SetupState, *, print_func=print) -> bool:
    if state.current_project is None:
        print_func("Select or create a project first.")
        return False
    return True


def action_create_project(state: SetupState, *, print_func=print, input_func=input) -> Path:
    workspace_root = require_workspace_root(state)
    project_name = prompt_required_text("Type project name:", input_func=input_func)
    paths = service.create_project(workspace_root, project_name)
    state.current_project = project_name
    print_func(f"Created project at {paths['project']}")
    return paths["project"]


def action_open_project(state: SetupState, *, print_func=print, input_func=input) -> Path | None:
    workspace_root = require_workspace_root(state)
    projects = service.get_projects(workspace_root)
    if not projects:
        print_func("No projects exist for this workspace yet.")
        return None

    for idx, project in enumerate(projects, start=1):
        print_func(f"{idx}. {project.name}")

    choice = prompt_menu_choice(
        len(projects),
        input_func=input_func,
        print_func=print_func,
    )
    if choice == 0:
        print_func("Project selection cancelled.")
        return None

    project = projects[choice - 1]
    state.current_project = project.name
    print_func(f"Current project set to {project.name}")
    return project


def action_copy_example_model(
    state: SetupState,
    *,
    print_func=print,
    input_func=input,
) -> Path | None:
    if not require_current_project(state, print_func=print_func):
        return None

    examples = list_available_example_names(state.repo_root)
    if not examples:
        print_func("No example models are available.")
        return None

    print_func("Available examples (choose a number):")
    print_func("0. Cancel")
    for idx, example_name in enumerate(examples, start=1):
        print_func(f"{idx}. {example_name}")

    model_name = prompt_required_text("Type model name:", input_func=input_func)
    example_choice = prompt_menu_choice(
        len(examples),
        input_func=input_func,
        print_func=print_func,
    )
    if example_choice == 0:
        print_func("Example selection cancelled.")
        return None

    example_name = examples[example_choice - 1]
    workspace_root = require_workspace_root(state)
    paths = service.copy_example_model(
        workspace_root,
        state.current_project,
        model_name,
        example_name,
    )
    print_func(f"Copied example model to {paths['model']}")
    return paths["model"]


def action_import_model(
    state: SetupState,
    *,
    print_func=print,
    input_func=input,
) -> Path | None:
    if not require_current_project(state, print_func=print_func):
        return None

    model_name = prompt_required_text("Type model name:", input_func=input_func)
    source_dir = prompt_required_text("Type source folder path:", input_func=input_func)
    workspace_root = require_workspace_root(state)
    paths = service.import_model(
        workspace_root,
        state.current_project,
        model_name,
        source_dir,
    )
    print_func(f"Imported model to {paths['model']}")
    return paths["model"]


def action_set_active_model(
    state: SetupState,
    *,
    print_func=print,
    input_func=input,
) -> Path | None:
    if not require_current_project(state, print_func=print_func):
        return None

    workspace_root = require_workspace_root(state)
    models = service.get_models(workspace_root, state.current_project)
    if not models:
        print_func("No models exist for this project yet.")
        return None

    for idx, model in enumerate(models, start=1):
        print_func(f"{idx}. {model.name}")

    choice = prompt_menu_choice(
        len(models),
        input_func=input_func,
        print_func=print_func,
    )
    if choice == 0:
        print_func("Active model selection cancelled.")
        return None

    model_name = models[choice - 1].name
    config_path = service.set_active_model(
        workspace_root,
        project_name=state.current_project,
        model_name=model_name,
    )
    print_func(f"Active model set to {model_name}")
    return config_path


def action_generate_nhm_notebooks(
    state: SetupState,
    *,
    print_func=print,
) -> list[Path] | None:
    if not require_current_project(state, print_func=print_func):
        return None

    workspace_root = require_workspace_root(state)
    created = notebook_builder.convert_workflow(
        "nhm",
        workspace_root=workspace_root,
        project_name=state.current_project,
        dry_run=False,
    )
    notebook_dir = bridge.get_project_workflow_notebooks_dir(
        "nhm",
        workspace_root,
        state.current_project,
    )
    print_func(f"Generated NHM notebooks in {notebook_dir}")
    return created


def action_launch_jupyter(
    state: SetupState,
    *,
    print_func=print,
) -> Path | None:
    if not require_current_project(state, print_func=print_func):
        return None

    workspace_root = require_workspace_root(state)
    project_root = bridge.get_project_dir(
        workspace_root,
        state.current_project,
    )
    subprocess.Popen(
        [sys.executable, "-m", "jupyter", "lab", str(project_root)],
        cwd=project_root,
    )
    print_func(f"Launching Jupyter for {project_root}")
    return project_root


def action_show_current_setup(
    state: SetupState,
    *,
    print_func=print,
) -> None:
    print_func("")
    print_func("Current setup")
    print_func(f"Workspace root: {state.workspace_root or '(not set)'}")
    print_func(f"Current project: {state.current_project or '(not selected)'}")

    if state.workspace_root is None or state.current_project is None:
        return

    project_root = bridge.get_project_dir(state.workspace_root, state.current_project)
    notebook_dir = bridge.get_project_workflow_notebooks_dir(
        "nhm",
        state.workspace_root,
        state.current_project,
    )
    models = service.get_models(state.workspace_root, state.current_project)
    active_model = get_active_model_name_for_state(state) or "(not set)"

    print_func(f"Project path: {project_root}")
    print_func(
        "Models: "
        + (", ".join(model.name for model in models) if models else "(none)")
    )
    print_func(f"Active model: {active_model}")
    print_func(f"NHM notebooks: {notebook_dir}")


def print_main_menu(state: SetupState, *, print_func=print) -> None:
    active_model = get_active_model_name_for_state(state) or "(not set)"
    print_func("")
    print_func("NHM setup")
    print_func("")
    print_func(f"Workspace root: {state.workspace_root or '(not set)'}")
    print_func(f"Current project: {state.current_project or '(not selected)'}")
    print_func(f"Active model: {active_model}")
    print_func("")
    print_func("1. Set workspace root")
    print_func("2. Create project")
    print_func("3. Open project")
    print_func("4. Copy example model")
    print_func("5. Import model folder")
    print_func("6. Set active model")
    print_func("7. Generate NHM notebooks")
    print_func("8. Launch Jupyter")
    print_func("9. Show current setup")
    print_func("0. Exit")


def run_setup(
    *,
    repo_root: str | Path | None = None,
    print_func=print,
    input_func=input,
) -> int:
    resolved_repo_root = (
        bridge.resolve_repo_root()
        if repo_root is None
        else Path(repo_root).expanduser().resolve()
    )
    state = SetupState(
        repo_root=resolved_repo_root,
        workspace_root=load_workspace_root_from_dotenv(resolved_repo_root),
    )

    try:
        if state.workspace_root is None:
            print_func("No workspace root is configured.")
            action_set_workspace_root(
                state,
                print_func=print_func,
                input_func=input_func,
            )
        else:
            print_func(f"Workspace root: {state.workspace_root}")

        while True:
            print_main_menu(state, print_func=print_func)
            choice = prompt_menu_choice(9, input_func=input_func, print_func=print_func)

            if choice == 0:
                print_func("Exiting setup.")
                return 0

            if choice == 1:
                action_set_workspace_root(
                    state,
                    print_func=print_func,
                    input_func=input_func,
                )
                continue

            try:
                if choice == 2:
                    action_create_project(
                        state,
                        print_func=print_func,
                        input_func=input_func,
                    )
                elif choice == 3:
                    action_open_project(
                        state,
                        print_func=print_func,
                        input_func=input_func,
                    )
                elif choice == 4:
                    action_copy_example_model(
                        state,
                        print_func=print_func,
                        input_func=input_func,
                    )
                elif choice == 5:
                    action_import_model(
                        state,
                        print_func=print_func,
                        input_func=input_func,
                    )
                elif choice == 6:
                    action_set_active_model(
                        state,
                        print_func=print_func,
                        input_func=input_func,
                    )
                elif choice == 7:
                    action_generate_nhm_notebooks(state, print_func=print_func)
                elif choice == 8:
                    action_launch_jupyter(state, print_func=print_func)
                elif choice == 9:
                    action_show_current_setup(state, print_func=print_func)
            except (FileNotFoundError, NotADirectoryError, ValueError, OSError) as exc:
                print_func(f"Error: {exc}")
    except KeyboardInterrupt:
        print_func("\nSetup cancelled.")
        return 130
