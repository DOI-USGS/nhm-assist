from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values, set_key


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
        raw = input_func("Select option: ").strip()
        try:
            choice = int(raw)
        except ValueError:
            print_func("Enter a number.")
            continue

        if 0 <= choice <= max_choice:
            return choice
        print_func(f"Enter a number between 0 and {max_choice}.")
