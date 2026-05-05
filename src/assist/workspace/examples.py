from pathlib import Path

from assist.workspace.bridge import resolve_repo_root


EXAMPLE_SOURCE_DIR_NAMES = ("examples", "domain_data")


def resolve_example_source(example_name: str) -> Path:
    repo_root = resolve_repo_root()
    for dir_name in EXAMPLE_SOURCE_DIR_NAMES:
        candidate = repo_root / dir_name / example_name
        if candidate.is_dir():
            return candidate

    raise FileNotFoundError(f"could not find example project '{example_name}'")
