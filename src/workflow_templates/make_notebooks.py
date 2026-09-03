from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Literal

import jupytext
from jupytext.paired_paths import InconsistentPath, paired_paths

from assist.workspace.bridge import get_project_workflow_notebooks_dir
from assist.workspace.kernels import PAIRING_MODE_KERNELS, ensure_kernel_registered


TEMPLATES_ROOT = Path(__file__).resolve().parent

COMMON_DIR = TEMPLATES_ROOT / "common"

# The numbered workflow notebooks live once, in common/. nhm renders only those;
# nhf layers its own workflow-specific templates (the FMI variant and its
# parameter-building utilities) on top; pest is still separate.
WORKFLOW_INPUT_DIRS: dict[str, tuple[Path, ...]] = {
    "nhm": (COMMON_DIR,),
    "nhf": (COMMON_DIR, TEMPLATES_ROOT / "nhf"),
    "pest": (TEMPLATES_ROOT / "pest",),
}

PairingMode = Literal["local", "dev"]


def dev_pairing_formats(template_dir: Path, notebook_dir: Path) -> str:
    """jupytext ``formats`` pairing a workspace notebook back to a repo template.

    jupytext resolves a ``formats`` prefix by concatenating it onto the
    notebook's own directory, so an absolute path yields a nonsense target
    (``/ws/proj/notebooks/nhm//repo/src/...``). The prefix must be relative,
    and must be posix-separated on every platform. The ``//`` before the
    format name is jupytext's prefix/format separator and is required — with a
    single slash the filename is concatenated onto the directory name.
    """
    try:
        relative = os.path.relpath(template_dir, notebook_dir)
    except ValueError as exc:  # Windows raises across drive letters.
        raise ValueError(
            "dev pairing needs the workspace and the nhm-assist repo on the "
            f"same drive: {notebook_dir} vs {template_dir}"
        ) from exc

    formats = f"ipynb,{Path(relative).as_posix()}//py:percent"
    _assert_pairing_resolves(formats, template_dir, notebook_dir)
    return formats


def _assert_pairing_resolves(
    formats: str,
    template_dir: Path,
    notebook_dir: Path,
) -> None:
    """Fail loudly if jupytext would not resolve ``formats`` back to the template.

    jupytext consumes one component of the notebook's directory per leading
    ``../``. If the climb reaches the filesystem root the directory is spent,
    the result silently loses its leading separator, and jupytext writes into
    the process's working directory instead of the repo — destroying the edit
    the contributor just made. That happens whenever the workspace and the repo
    share no ancestor but the root: different top-level directories, a separate
    volume, or a different Windows drive.

    Rather than reimplement that rule, ask jupytext itself where the pairing
    lands, using a probe filename.
    """
    probe = "__nhm_assist_pairing_probe__"
    try:
        paired = [
            path
            for path, fmt in paired_paths(
                str(notebook_dir / f"{probe}.ipynb"), "ipynb", formats
            )
            if fmt.get("extension") == ".py"
        ]
    except InconsistentPath as exc:
        paired = []
        reason: Exception | None = exc
    else:
        reason = None

    if len(paired) == 1 and Path(paired[0]) == template_dir / f"{probe}.py":
        return

    landing = paired[0] if paired else "(jupytext could not resolve a path)"
    raise ValueError(
        "dev pairing cannot reach the nhm-assist repo from this workspace.\n"
        f"  workspace notebooks: {notebook_dir}\n"
        f"  repo templates:      {template_dir}\n"
        f"  pairing would land:  {landing}\n"
        "jupytext pairs through a relative path, which only works when the "
        "workspace and the repo share a parent directory below the filesystem "
        "root. Move your workspace under the same top-level directory as the "
        "repo (for example, both under your home directory) and try again. "
        "Ordinary notebook generation (notebooks-create-project) is unaffected "
        "and works from anywhere."
        + (f"\n  jupytext said: {reason}" if reason is not None else "")
    )


def _apply_pairing(
    notebook,
    *,
    pairing_mode: PairingMode,
    template_dir: Path,
    notebook_dir: Path,
) -> None:
    kernel_name, kernel_display = PAIRING_MODE_KERNELS[pairing_mode]

    jupytext_meta = notebook.metadata.setdefault("jupytext", {})
    if pairing_mode == "dev":
        jupytext_meta["formats"] = dev_pairing_formats(template_dir, notebook_dir)
        # Without this, every sync stamps the workspace's own relative
        # formats path and local jupytext_version into the shared, committed
        # repo template, churning on every contributor's save. The .ipynb
        # (never committed to nhm-assist) keeps full metadata regardless, so
        # pairing and the kernel selection are unaffected.
        jupytext_meta["notebook_metadata_filter"] = "-all"
    else:
        # Pairing comes from the project's jupytext.toml, not from the file.
        jupytext_meta.pop("formats", None)
        jupytext_meta.pop("notebook_metadata_filter", None)
    if not jupytext_meta:
        notebook.metadata.pop("jupytext", None)

    notebook.metadata["kernelspec"] = {
        "name": kernel_name,
        "display_name": kernel_display,
        "language": "python",
    }


def _patch_existing_notebook(
    output_path: Path,
    py_file: Path,
    *,
    pairing_mode: PairingMode,
    dry_run: bool,
) -> str:
    """Bring an existing notebook's metadata in line without touching its cells."""
    notebook = jupytext.read(output_path)
    kernel_name, _ = PAIRING_MODE_KERNELS[pairing_mode]
    if pairing_mode == "dev":
        wanted_formats = dev_pairing_formats(py_file.parent, output_path.parent)
        wanted_metadata_filter = "-all"
    else:
        # Local mode needs no relationship to the repo path at all -- a real
        # end user's workspace has none -- so this must not call
        # dev_pairing_formats, which requires the repo to be reachable.
        wanted_formats = None
        wanted_metadata_filter = None

    current_jupytext_meta = notebook.metadata.get("jupytext", {})
    current_formats = current_jupytext_meta.get("formats")
    current_metadata_filter = current_jupytext_meta.get("notebook_metadata_filter")
    current_kernel = (notebook.metadata.get("kernelspec") or {}).get("name")
    if (
        current_formats == wanted_formats
        and current_metadata_filter == wanted_metadata_filter
        and current_kernel == kernel_name
    ):
        return "already configured"

    if not dry_run:
        _apply_pairing(
            notebook,
            pairing_mode=pairing_mode,
            template_dir=py_file.parent,
            notebook_dir=output_path.parent,
        )
        jupytext.write(notebook, output_path)
    return "metadata updated"


def iter_workflow_templates(name: str) -> list[tuple[Path, Path]]:
    """Return (template_path, output-relative path) for one workflow.

    A later input directory may not shadow an earlier one. If a workflow
    directory ever reintroduces a template whose name collides with a shared
    one, that is precisely the duplication this layout exists to remove, so it
    raises instead of silently overriding.
    """
    collected: list[tuple[Path, Path]] = []
    seen: dict[Path, Path] = {}

    for input_dir in WORKFLOW_INPUT_DIRS[name]:
        if not input_dir.exists():
            raise FileNotFoundError(f"Missing workflow template folder: {input_dir}")
        for py_file in sorted(input_dir.rglob("*.py")):
            relative = py_file.relative_to(input_dir)
            if relative in seen:
                raise ValueError(
                    f"{name}: {relative} exists in both {seen[relative]} and "
                    f"{input_dir}; the copy in common/ must be the only one"
                )
            seen[relative] = input_dir
            collected.append((py_file, relative))

    return collected


def convert_workflow(
    name: str,
    *,
    workspace_root: str | Path,
    project_name: str,
    dry_run: bool = False,
    pairing_mode: PairingMode = "local",
    print_func=print,
) -> list[Path]:
    if pairing_mode not in PAIRING_MODE_KERNELS:
        raise ValueError(f"unsupported pairing mode: {pairing_mode}")
    if not project_name:
        raise ValueError("project_name is required")

    # One shared template set plus each workflow's own extras, instead of a
    # single input directory per workflow.
    templates = iter_workflow_templates(name)

    output_folder = get_project_workflow_notebooks_dir(
        name, workspace_root, project_name
    )
    output_folder.mkdir(parents=True, exist_ok=True)

    created_paths: list[Path] = []

    for py_file, relative_path in templates:
        output_path = output_folder / relative_path.with_suffix(".ipynb")
        created_paths.append(output_path)

        if output_path.exists():
            status = _patch_existing_notebook(
                output_path,
                py_file,
                pairing_mode=pairing_mode,
                dry_run=dry_run,
            )
        else:
            status = "created"
            if not dry_run:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                notebook = jupytext.read(py_file)
                _apply_pairing(
                    notebook,
                    pairing_mode=pairing_mode,
                    template_dir=py_file.parent,
                    notebook_dir=output_path.parent,
                )
                jupytext.write(notebook, output_path)

        print_func(f"[{name}] {status}: {output_path}")

    return created_paths


def parse_args(argv: list[str] | None = None, *, default_workflow: str = "nhm"):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workflow",
        choices=["nhm", "nhf", "pest", "all"],
        default=default_workflow,
        help="Workflow template set to convert.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned conversions without writing notebooks.",
    )
    parser.add_argument(
        "--workspace-root",
        help="External workspace root for notebook output.",
    )
    parser.add_argument(
        "--project-name",
        help="Project name for project-shared workspace notebook output.",
    )
    parser.add_argument(
        "--pairing-mode",
        choices=["local", "dev"],
        default="local",
        help=(
            "local: pair via the project's jupytext.toml (same-directory .py). "
            "dev: pair back to src/workflow_templates/<workflow>/*.py in the repo."
        ),
    )
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    *,
    default_workflow: str = "nhm",
    print_func=print,
) -> int:
    args = parse_args(argv, default_workflow=default_workflow)

    if not args.workspace_root or not args.project_name:
        print_func("Error: --workspace-root and --project-name are both required.")
        return 2

    kernel_name, kernel_display = PAIRING_MODE_KERNELS[args.pairing_mode]
    if not args.dry_run:
        ensure_kernel_registered(kernel_name, kernel_display)

    workflows = list(WORKFLOW_INPUT_DIRS) if args.workflow == "all" else [args.workflow]

    for workflow in workflows:
        created = convert_workflow(
            workflow,
            workspace_root=args.workspace_root,
            project_name=args.project_name,
            dry_run=args.dry_run,
            pairing_mode=args.pairing_mode,
            print_func=print_func,
        )
        notebook_dir = get_project_workflow_notebooks_dir(
            workflow, args.workspace_root, args.project_name
        )
        print_func("")
        print_func(f"[{workflow}] {len(created)} notebook(s) in {notebook_dir}")
        print_func(f"[{workflow}] Open them with: jupyter lab {notebook_dir}")
        print_func(
            f"[{workflow}] Or open that folder in VS Code / Kiro and select the "
            f"'{kernel_display}' kernel."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
