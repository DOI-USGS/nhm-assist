import os
from pathlib import Path
from typing import Mapping

from assist.workspace.bridge import resolve_repo_root


EXAMPLE_ENV_VAR = "NHM_ASSIST_EXAMPLES_DIR"
EXAMPLE_SOURCE_DIR_NAMES = ("domain_data",)


def _candidate_example_roots(
    *,
    env: Mapping[str, str] | None = None,
) -> list[Path]:
    env_map = os.environ if env is None else env

    roots: list[Path] = []
    override = env_map.get(EXAMPLE_ENV_VAR)
    if override:
        roots.append(Path(override).expanduser().resolve())

    repo_root = resolve_repo_root(env=env_map)
    for dir_name in EXAMPLE_SOURCE_DIR_NAMES:
        roots.append(repo_root / dir_name)

    return roots


def resolve_example_source(
    example_name: str,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    searched: list[Path] = []
    for root in _candidate_example_roots(env=env):
        candidate = root / example_name
        searched.append(candidate)
        if candidate.is_dir():
            return candidate

    locations = "\n  ".join(str(p) for p in searched)
    raise FileNotFoundError(
        f"Example '{example_name}' not found. Searched:\n  {locations}\n"
        f"Run `python pull_domain.py --name {example_name}` from the repo root "
        f"to download it from USGS HyTEST OSN, or set {EXAMPLE_ENV_VAR} to a "
        f"directory containing a `{example_name}/` subfolder."
    )


def list_available_example_names(
    *,
    env: Mapping[str, str] | None = None,
) -> list[str]:
    names: set[str] = set()
    for root in _candidate_example_roots(env=env):
        if not root.is_dir():
            continue
        for child in root.iterdir():
            if child.is_dir():
                names.add(child.name)
    return sorted(names)
