from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values, set_key, unset_key

from assist.workspace import bridge, service
from assist.workspace.examples import list_available_example_names
from assist.workspace.kernels import (
    DEFAULT_KERNEL_DISPLAY_NAME,
    DEFAULT_KERNEL_NAME,
    ensure_kernel_registered,
)
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


USGS_API_KEY_ENV_VAR = "API_USGS_PAT"
USGS_API_KEY_SIGNUP_URL = "https://api.waterdata.usgs.gov/signup/"


def load_api_key_from_dotenv(repo_root: Path) -> str | None:
    dotenv_path = get_repo_dotenv_path(repo_root)
    if not dotenv_path.exists():
        return None
    value = dotenv_values(dotenv_path).get(USGS_API_KEY_ENV_VAR)
    if not value:
        return None
    return value.strip() or None


def save_api_key_to_dotenv(repo_root: Path, api_key: str) -> Path:
    dotenv_path = get_repo_dotenv_path(repo_root)
    if not dotenv_path.exists():
        dotenv_path.touch()
    set_key(str(dotenv_path), USGS_API_KEY_ENV_VAR, api_key.strip())
    return dotenv_path


def clear_api_key_from_dotenv(repo_root: Path) -> Path:
    dotenv_path = get_repo_dotenv_path(repo_root)
    if dotenv_path.exists():
        unset_key(str(dotenv_path), USGS_API_KEY_ENV_VAR)
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


DEFAULT_WORKSPACE_ROOT = Path("~/nhm-workspace")


def _is_under_repo(workspace_root: Path, repo_root: Path) -> bool:
    try:
        workspace_root.relative_to(repo_root)
    except ValueError:
        return False
    return True


def prompt_workspace_root(
    repo_root: Path,
    *,
    print_func=print,
    input_func=input,
) -> Path:
    default_root = DEFAULT_WORKSPACE_ROOT.expanduser().resolve()
    print_func(
        "Your workspace folder holds projects, models, generated notebooks, and outputs."
    )
    print_func(
        "Pick a location outside the cloned repository so generated files stay out of git."
    )
    print_func(f"Press Enter to accept the default ({default_root}).")

    while True:
        raw_path = input_func("Workspace root path: ").strip()
        if not raw_path:
            workspace_root = default_root
        else:
            workspace_root = Path(raw_path).expanduser().resolve()

        if workspace_root.exists() and not workspace_root.is_dir():
            print_func(f"Path is not a directory: {workspace_root}")
            continue

        if _is_under_repo(workspace_root, repo_root):
            print_func(
                f"Warning: {workspace_root} is inside the repository at {repo_root}."
            )
            print_func(
                "Workspace files will be mixed into your git checkout; "
                "this is strongly discouraged."
            )
            if not prompt_yes_no(
                "Use this path anyway?",
                default=False,
                input_func=input_func,
            ):
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
    previous_workspace_root = state.workspace_root
    previous_project = state.current_project
    workspace_root = prompt_workspace_root(
        state.repo_root,
        print_func=print_func,
        input_func=input_func,
    )
    state.workspace_root = workspace_root

    if (
        previous_project is not None
        and previous_workspace_root != workspace_root
    ):
        candidate = bridge.get_project_dir(workspace_root, previous_project)
        if not bridge.is_project_dir(candidate):
            state.current_project = None
            print_func(
                f"Cleared current project '{previous_project}': "
                f"not present in new workspace."
            )

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


def _set_model_active(
    state: SetupState,
    model_name: str,
    *,
    workspace_root: Path,
    print_func=print,
) -> None:
    try:
        service.set_active_model(
            workspace_root,
            project_name=state.current_project,
            model_name=model_name,
        )
        print_func(f"Active model set to {model_name}")
    except (FileNotFoundError, NotADirectoryError, ValueError, OSError) as exc:
        print_func(
            f"Model '{model_name}' is available but could not be set active: {exc}. "
            f"Use 'Set active model' to activate it."
        )


def action_copy_example_model(
    state: SetupState,
    *,
    print_func=print,
    input_func=input,
) -> Path | None:
    if not require_current_project(state, print_func=print_func):
        return None

    examples = list_available_example_names()
    if not examples:
        print_func("No example models are available.")
        return None

    print_func("Available examples (choose a number):")
    print_func("0. Cancel")
    for idx, example_name in enumerate(examples, start=1):
        print_func(f"{idx}. {example_name}")

    example_choice = prompt_menu_choice(
        len(examples),
        input_func=input_func,
        print_func=print_func,
    )
    if example_choice == 0:
        print_func("Example selection cancelled.")
        return None

    example_name = examples[example_choice - 1]
    model_name = example_name
    workspace_root = require_workspace_root(state)
    paths = service.copy_example_model(
        workspace_root,
        state.current_project,
        model_name,
        example_name,
    )
    print_func(f"Copied example model to {paths['model']}")
    _set_model_active(
        state,
        model_name,
        workspace_root=workspace_root,
        print_func=print_func,
    )
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
    _set_model_active(
        state,
        model_name,
        workspace_root=workspace_root,
        print_func=print_func,
    )
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


def generate_nhm_notebooks(
    state: SetupState,
    *,
    print_func=print,
) -> list[Path]:
    workspace_root = require_workspace_root(state)
    ensure_kernel_registered(DEFAULT_KERNEL_NAME, DEFAULT_KERNEL_DISPLAY_NAME)
    created = notebook_builder.convert_workflow(
        "nhm",
        workspace_root=workspace_root,
        project_name=state.current_project,
        dry_run=False,
        print_func=lambda *_: None,
    )
    notebook_dir = bridge.get_project_workflow_notebooks_dir(
        "nhm",
        workspace_root,
        state.current_project,
    )
    print_func(f"Generated NHM notebooks in {notebook_dir}")
    return created


def nhm_notebooks_need_generation(state: SetupState) -> bool:
    if state.workspace_root is None or state.current_project is None:
        return True

    template_dir = notebook_builder.WORKFLOW_INPUT_DIRS["nhm"]
    notebook_dir = bridge.get_project_workflow_notebooks_dir(
        "nhm",
        state.workspace_root,
        state.current_project,
    )

    if not notebook_dir.exists() or not any(notebook_dir.rglob("*.ipynb")):
        return True

    for py_file in template_dir.rglob("*.py"):
        relative = py_file.relative_to(template_dir).with_suffix(".ipynb")
        target = notebook_dir / relative
        if not target.exists():
            return True
        if py_file.stat().st_mtime > target.stat().st_mtime:
            return True

    return False


def action_generate_nhm_notebooks(
    state: SetupState,
    *,
    print_func=print,
) -> list[Path] | None:
    if not require_current_project(state, print_func=print_func):
        return None
    return generate_nhm_notebooks(state, print_func=print_func)


def action_show_notebook_location(
    state: SetupState,
    *,
    print_func=print,
) -> Path | None:
    if not require_current_project(state, print_func=print_func):
        return None

    workspace_root = require_workspace_root(state)

    if nhm_notebooks_need_generation(state):
        print_func("Generating NHM notebooks first…")
        generate_nhm_notebooks(state, print_func=print_func)

    notebook_dir = bridge.get_project_workflow_notebooks_dir(
        "nhm",
        workspace_root,
        state.current_project,
    )

    quoted = shlex.quote(str(notebook_dir))
    print_func("")
    print_func(f"Your NHM notebooks are in: {notebook_dir}")
    print_func("Open them yourself with whichever tool you use:")
    print_func(f"  jupyter lab {quoted}")
    print_func(f"  code {quoted}")
    print_func(f"Then select the '{DEFAULT_KERNEL_DISPLAY_NAME}' kernel.")
    print_func("Run 0_workspace_setup.ipynb first.")
    return notebook_dir


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


def action_set_api_key(
    state: SetupState,
    *,
    print_func=print,
    input_func=input,
) -> None:
    current = load_api_key_from_dotenv(state.repo_root)
    print_func("")
    print_func("USGS WaterData API key (API_USGS_PAT)")
    print_func(
        "Used by dataretrieval for higher rate limits on Water Data queries."
    )
    print_func(f"Register a key at: {USGS_API_KEY_SIGNUP_URL}")
    if current:
        masked = current[:4] + "…" + current[-4:] if len(current) > 8 else "set"
        print_func(f"Currently configured ({masked}).")
        print_func("Type a new key to replace, 'clear' to remove, or Enter to keep.")
    else:
        print_func("No key is currently configured.")
        print_func("Type the key to save, or press Enter to skip.")

    raw = input_func("API key: ").strip()
    if not raw:
        print_func("API key unchanged.")
        return
    if raw.lower() == "clear":
        clear_api_key_from_dotenv(state.repo_root)
        print_func("API key cleared from .env.")
        return
    save_api_key_to_dotenv(state.repo_root, raw)
    print_func(f"API key saved to {get_repo_dotenv_path(state.repo_root)}.")
    print_func("Restart the kernel for notebooks that already loaded the .env.")


def print_main_menu(state: SetupState, *, print_func=print) -> None:
    active_model = get_active_model_name_for_state(state) or "(not set)"
    api_key_status = (
        "configured" if load_api_key_from_dotenv(state.repo_root) else "not set"
    )
    print_func("")
    print_func("NHM setup")
    print_func("")
    print_func(f"Workspace root: {state.workspace_root or '(not set)'}")
    print_func(f"Current project: {state.current_project or '(not selected)'}")
    print_func(f"Active model: {active_model}")
    print_func(f"USGS WaterData API key: {api_key_status}")
    print_func("")
    print_func("  -- Guided setup (do these in order) --")
    print_func("  1. Set workspace root")
    print_func("  2. Create project")
    print_func("  3. Copy example model")
    print_func("  4. Show notebook folder and how to open it")
    print_func("")
    print_func("  -- More options --")
    print_func("  5. Open existing project")
    print_func("  6. Import model folder")
    print_func("  7. Set active model")
    print_func("  8. Generate NHM notebooks")
    print_func("  9. Show current setup")
    print_func(" 10. Set USGS WaterData API key")
    print_func("  0. Exit")


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
            choice = prompt_menu_choice(10, input_func=input_func, print_func=print_func)

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
                    action_copy_example_model(
                        state,
                        print_func=print_func,
                        input_func=input_func,
                    )
                elif choice == 4:
                    action_show_notebook_location(state, print_func=print_func)
                elif choice == 5:
                    action_open_project(
                        state,
                        print_func=print_func,
                        input_func=input_func,
                    )
                elif choice == 6:
                    action_import_model(
                        state,
                        print_func=print_func,
                        input_func=input_func,
                    )
                elif choice == 7:
                    action_set_active_model(
                        state,
                        print_func=print_func,
                        input_func=input_func,
                    )
                elif choice == 8:
                    action_generate_nhm_notebooks(state, print_func=print_func)
                elif choice == 9:
                    action_show_current_setup(state, print_func=print_func)
                elif choice == 10:
                    action_set_api_key(
                        state,
                        print_func=print_func,
                        input_func=input_func,
                    )
            except (FileNotFoundError, NotADirectoryError, ValueError, OSError) as exc:
                print_func(f"Error: {exc}")
    except KeyboardInterrupt:
        print_func("\nSetup cancelled.")
        return 130
