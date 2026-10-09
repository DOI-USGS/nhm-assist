"""Generate a project's notebooks: all nhm, plus a chosen subset of nhf.

Replicates a two-part notebook-generation task for a user workspace project:

  1. Generate every nhm notebook into ``<project>/notebooks/nhm/``.
  2. Generate the full nhf set into ``<project>/notebooks/nhf/``, then prune it
     down to a chosen keep-list.

Why generate-then-prune for nhf? The ``notebooks-create-project`` pixi task has
no option to render a subset: the ``nhf`` workflow always emits the common
numbered notebooks plus every template under ``src/workflow_templates/nhf/``.
Generating the full set with the project's own tooling keeps jupytext pairing
and kernelspec handling correct; this script then deletes the extras (including
any ``.ipynb_checkpoints`` directory) so only the requested nhf notebooks remain.

Both steps shell out to ``pixi run notebooks-create-project``, so this must be
run from a checkout of the nhm-assist repo (where ``pyproject.toml`` defines
that task). The workspace and project may live anywhere.

Workspace root and project come from the pixi setup where possible:

  * Workspace root is read from the repo's ``.env`` (``NHM_ASSIST_WORKSPACE_ROOT``,
    written by ``pixi run setup`` -> "Set workspace root"), falling back to the
    setup default ``<repo parent>/nhm-workspace``. ``--workspace-root`` overrides.
  * The project is NOT persisted by setup, so with no ``--project-name`` this
    script discovers the projects in the workspace: if there is exactly one it
    uses it, otherwise it lists them and asks you to pick (or pass
    ``--project-name``).

Default keep-list (the nhf notebooks the training project needs):
    Create_subbasin_model_NHM_v1.ipynb
    Create_gridmet_climate_drivers.ipynb
    gf_params_parse_v1_1.ipynb

Usage:
    # Read workspace root from .env, auto-detect / prompt for the project,
    # keep the two nhf notebooks above:
    pixi run python scripts/Make_NHM_v1_1_training_notebooks.py

    # A specific workspace / project:
    pixi run python scripts/Make_NHM_v1_1_training_notebooks.py \\
        --workspace-root /path/to/workspace --project-name MyProject

    # A different set of nhf notebooks to keep (repeat --keep-nhf, with or
    # without the .ipynb extension):
    pixi run python scripts/Make_NHM_v1_1_training_notebooks.py \\
        --keep-nhf Create_subbasin_model_NHM_v2 --keep-nhf gf_params_parse

    # Keep the whole nhf set (no pruning):
    pixi run python scripts/Make_NHM_v1_1_training_notebooks.py --keep-all-nhf

    # Contributor (dev) pairing: notebooks pair back to the repo templates, so
    # editing a notebook edits src/workflow_templates/<workflow>/*.py:
    pixi run python scripts/Make_NHM_v1_1_training_notebooks.py --pairing-mode dev

    # Preview without generating or deleting anything:
    pixi run python scripts/Make_NHM_v1_1_training_notebooks.py --dry-run
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console

from assist.workspace import bridge
from assist.workspace.setup import (
    default_workspace_root,
    load_workspace_root_from_dotenv,
)

console = Console()

# The project is not persisted by setup; only the keep-list has a fixed default.
DEFAULT_KEEP_NHF = (
    "Create_subbasin_model_NHM_v1.ipynb",
    "Create_gridmet_climate_drivers.ipynb",
    "gf_params_parse_v1_1.ipynb",
)

# The pixi tasks defined in the repo's pyproject.toml, by pairing mode. Both
# render the same notebooks; they differ only in how the .ipynb is paired to
# its .py template (local = same-directory via jupytext.toml; dev = back to
# src/workflow_templates/<workflow>/).
PIXI_TASK_BY_MODE = {
    "local": "notebooks-create-project",
    "dev": "dev-mode",
}


def repo_root() -> Path:
    """The nhm-assist checkout this script lives in (scripts/ -> repo root)."""
    return Path(__file__).resolve().parent.parent


def resolve_workspace_root(cli_value: str | None) -> Path:
    """Pick the workspace root: CLI flag, else .env, else the setup default.

    Mirrors `pixi run setup`: the workspace root it saves lives in the repo's
    .env as NHM_ASSIST_WORKSPACE_ROOT, and its own fallback is
    <repo parent>/nhm-workspace.
    """
    if cli_value:
        return Path(cli_value).expanduser().resolve()

    root = repo_root()
    from_dotenv = load_workspace_root_from_dotenv(root)
    if from_dotenv is not None:
        console.print(
            f"[dim]Workspace root from .env (NHM_ASSIST_WORKSPACE_ROOT): "
            f"{from_dotenv}[/dim]"
        )
        return from_dotenv

    fallback = default_workspace_root(root)
    console.print(
        f"[dim]No --workspace-root and no NHM_ASSIST_WORKSPACE_ROOT in .env; "
        f"using setup default: {fallback}[/dim]"
    )
    return fallback


def resolve_project_name(cli_value: str | None, workspace_root: Path) -> str:
    """Pick the project: CLI flag, else the sole project, else prompt.

    Setup does not persist a "current project", so when one is not given we
    discover the projects in the workspace (the same way the setup CLI lists
    them). One project -> use it; several -> ask; none -> error.
    """
    if cli_value:
        return cli_value

    try:
        projects = bridge.list_projects(workspace_root)
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        console.print(
            f"[red]Could not read projects from {workspace_root}: {exc}[/red]"
        )
        raise SystemExit(2) from exc

    names = [p.name for p in projects]
    if not names:
        console.print(
            f"[red]No projects found in {workspace_root}.[/red] "
            "Create one with `pixi run setup` (or `pixi run project-create`), "
            "then re-run this script."
        )
        raise SystemExit(2)

    if len(names) == 1:
        console.print(f"[dim]Using the only project in the workspace: {names[0]}[/dim]")
        return names[0]

    console.print(f"[bold]Projects in {workspace_root}:[/bold]")
    for idx, name in enumerate(names, start=1):
        console.print(f"  {idx}. {name}")
    console.print("  0. Cancel")

    while True:
        try:
            raw = input(f"Select a project [0-{len(names)}]: ").strip()
        except EOFError:
            console.print(
                "\n[red]No project selected and input is not interactive.[/red] "
                "Pass --project-name."
            )
            raise SystemExit(2) from None
        if not raw.isdigit():
            console.print("Please enter a number.")
            continue
        choice = int(raw)
        if choice == 0:
            console.print("Cancelled.")
            raise SystemExit(1)
        if 1 <= choice <= len(names):
            return names[choice - 1]
        console.print(f"Please enter a number between 0 and {len(names)}.")


def run_workflow(
    workflow: str,
    workspace_root: str | Path,
    project_name: str,
    *,
    pairing_mode: str,
    dry_run: bool,
) -> None:
    """Invoke the pixi notebook-generation task for one workflow.

    `pairing_mode` selects the task: "local" -> notebooks-create-project,
    "dev" -> dev-mode. Both take the same positional arguments.
    """
    task = PIXI_TASK_BY_MODE[pairing_mode]
    cmd = [
        "pixi",
        "run",
        task,
        str(workspace_root),
        project_name,
        workflow,
    ]
    console.print(f"[bold cyan]$ {' '.join(cmd)}[/bold cyan]")
    if dry_run:
        console.print("[dim](dry run: not executed)[/dim]")
        return

    # cwd must be the repo so pixi finds pyproject.toml and the task.
    result = subprocess.run(cmd, cwd=repo_root(), check=False)
    if result.returncode != 0:
        console.print(
            f"[red]pixi task failed for workflow '{workflow}' "
            f"(exit {result.returncode}).[/red]"
        )
        raise SystemExit(result.returncode)


def normalize_keep(names: list[str]) -> set[str]:
    """Accept names with or without the .ipynb suffix; return .ipynb filenames."""
    normalized: set[str] = set()
    for name in names:
        normalized.add(name if name.endswith(".ipynb") else f"{name}.ipynb")
    return normalized


def prune_nhf(
    nhf_dir: Path,
    keep: set[str],
    *,
    dry_run: bool,
) -> None:
    """Delete everything in nhf_dir except the keep-list notebooks.

    Removes stray files and directories too (notably .ipynb_checkpoints), so the
    folder ends up holding exactly the requested notebooks.
    """
    if not nhf_dir.is_dir():
        console.print(f"[yellow]No nhf folder to prune at[/yellow] {nhf_dir}")
        return

    present = {p.name for p in nhf_dir.iterdir()}
    missing = keep - present
    if missing:
        console.print(
            "[yellow]Warning: requested nhf notebook(s) were not generated "
            f"and cannot be kept: {', '.join(sorted(missing))}[/yellow]"
        )

    removed = 0
    for entry in sorted(nhf_dir.iterdir()):
        if entry.name in keep:
            continue
        console.print(f"  [red]remove[/red] {entry.name}")
        if not dry_run:
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        removed += 1

    kept = sorted(keep & present)
    console.print(
        f"[green]Pruned nhf:[/green] removed {removed} item(s), "
        f"kept {len(kept)}: {', '.join(kept) if kept else '(none)'}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--workspace-root",
        default=None,
        help=(
            "Workspace root containing the project. Default: NHM_ASSIST_WORKSPACE_ROOT "
            "from the repo's .env, else <repo parent>/nhm-workspace."
        ),
    )
    parser.add_argument(
        "--project-name",
        default=None,
        help=(
            "Project to generate notebooks for. Default: the sole project in the "
            "workspace, or you are prompted to choose."
        ),
    )
    parser.add_argument(
        "--keep-nhf",
        action="append",
        default=None,
        metavar="NOTEBOOK",
        help=(
            "nhf notebook to keep after pruning (repeatable; .ipynb optional). "
            f"Default: {', '.join(DEFAULT_KEEP_NHF)}."
        ),
    )
    parser.add_argument(
        "--keep-all-nhf",
        action="store_true",
        help="Keep the entire generated nhf set (skip pruning).",
    )
    parser.add_argument(
        "--skip-nhm",
        action="store_true",
        help="Do not generate the nhm notebooks.",
    )
    parser.add_argument(
        "--skip-nhf",
        action="store_true",
        help="Do not generate (or prune) the nhf notebooks.",
    )
    parser.add_argument(
        "--pairing-mode",
        choices=["local", "dev"],
        default="local",
        help=(
            "How to pair the generated notebooks. local (default): same-directory "
            ".py via the project's jupytext.toml. dev: pair back to "
            "src/workflow_templates/<workflow>/*.py so editing a notebook edits "
            "the repo template (contributor mode)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would run and what would be removed, without doing it.",
    )
    args = parser.parse_args()

    workspace_root = resolve_workspace_root(args.workspace_root)
    project_name = resolve_project_name(args.project_name, workspace_root)
    keep_names = args.keep_nhf if args.keep_nhf is not None else list(DEFAULT_KEEP_NHF)
    keep = normalize_keep(keep_names)

    project_dir = workspace_root / project_name
    console.print(f"[bold]Project:[/bold] {project_dir}")
    console.print(f"[dim]Pairing mode: {args.pairing_mode}[/dim]")
    if args.dry_run:
        console.print("[dim]DRY RUN -- no files will be generated or deleted.[/dim]")

    # Part 1: all nhm notebooks.
    if not args.skip_nhm:
        console.print("\n[bold]Step 1: generate all nhm notebooks[/bold]")
        run_workflow(
            "nhm",
            workspace_root,
            project_name,
            pairing_mode=args.pairing_mode,
            dry_run=args.dry_run,
        )
    else:
        console.print("\n[dim]Skipping nhm generation (--skip-nhm).[/dim]")

    # Part 2: full nhf set, then prune to the keep-list.
    if not args.skip_nhf:
        console.print("\n[bold]Step 2: generate the nhf set[/bold]")
        run_workflow(
            "nhf",
            workspace_root,
            project_name,
            pairing_mode=args.pairing_mode,
            dry_run=args.dry_run,
        )

        nhf_dir = project_dir / "notebooks" / "nhf"
        if args.keep_all_nhf:
            console.print(
                "\n[dim]Keeping the entire nhf set (--keep-all-nhf); no pruning.[/dim]"
            )
        else:
            console.print(
                f"\n[bold]Step 3: prune nhf to {len(keep)} notebook(s)[/bold]"
            )
            prune_nhf(nhf_dir, keep, dry_run=args.dry_run)
    else:
        console.print("\n[dim]Skipping nhf generation (--skip-nhf).[/dim]")

    console.print("\n[bold green]Done.[/bold green]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
