"""The fabric re-export shims are gone; assist.common is the only path.

The nine-pair unification left `assist.nhm.*` / `assist.nhf.*` shims in place
so existing notebooks kept importing by their old names. Once the workflow
templates were unified too, every caller in the repo pointed at
`assist.common`, and the shims were dead weight that let a new caller quietly
re-introduce a per-fabric import. This file is the standing guard.

`assist.nhf` still exists as a package: it holds real nhf-only modules
(`make_pws_params`, `nhm_config`, and the HRRR download scripts), none of
which are shims. `assist.nhm` is gone entirely -- it held nothing but shims.
"""
import ast
import importlib
import pathlib

import pytest

from tests.unification.harness import REPO_ROOT

RETIRED_MODULES = [
    "assist.nhm.efc",
    "assist.nhm.map_template",
    "assist.nhm.nhm_assist_utilities",
    "assist.nhm.nhm_helpers",
    "assist.nhm.nhm_hydrofabric",
    "assist.nhm.nhm_output_visualization",
    "assist.nhm.output_plots",
    "assist.nhm.sf_data_retrieval",
    "assist.nhm.streamflow_postprocess",
    "assist.nhf.display_controls_v2",
    "assist.nhf.efc",
    "assist.nhf.map_template_v2",
    "assist.nhf.nhm_assist_utilities_v2",
    "assist.nhf.nhm_helpers_v2",
    "assist.nhf.nhm_hydrofabric_v2",
    "assist.nhf.nhm_output_visualization_v2",
    "assist.nhf.output_plots_v2",
    "assist.nhf.sf_data_retrieval_v2_1",
]

# nhf-only implementations, deliberately kept
KEPT_NHF_MODULES = [
    "make_pws_params.py",
    "nhm_config.py",
    "rebuild_hrrr_cache.py",
    "run_hrrr_download.py",
    "run_hrrr_download_s3.py",
]


@pytest.mark.parametrize("module", RETIRED_MODULES)
def test_retired_module_is_unimportable(module):
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module)


def test_the_nhm_package_is_gone():
    # Asserts on source, not on the directory: git does not remove an untracked
    # __pycache__ when it deletes the package, and a sourceless .pyc there is
    # not importable, so a leftover cache is not the package coming back.
    remaining = sorted((REPO_ROOT / "src/assist/nhm").rglob("*.py"))
    assert not remaining, remaining


def test_the_nhf_package_kept_only_its_real_modules():
    nhf = REPO_ROOT / "src/assist/nhf"
    present = sorted(
        p.name for p in nhf.glob("*.py") if p.name != "__init__.py"
    )
    assert present == sorted(KEPT_NHF_MODULES), present


def test_no_shim_files_remain():
    """A shim is a module whose body only re-exports from assist.common."""
    offenders = []
    for path in (REPO_ROOT / "src/assist").rglob("*.py"):
        if ".ipynb_checkpoints" in str(path):
            continue
        source = path.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        defs = [
            n.name
            for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        reexports = any(
            isinstance(n, ast.ImportFrom)
            and n.module
            and n.module.startswith("assist.common")
            for n in tree.body
        )
        if reexports and not defs and "common" not in path.parts:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == [], f"shim files are back: {offenders}"


def test_nothing_in_the_repo_imports_a_retired_path():
    """Templates, runners and helpers must all reach assist.common directly."""
    retired = set(RETIRED_MODULES)
    offenders = []
    for path in REPO_ROOT.rglob("*.py"):
        sp = str(path)
        if any(x in sp for x in (".pixi/", "/.git/", "__pycache__",
                                 ".ipynb_checkpoints", "/tests/")):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
                if node.module in ("assist.nhm", "assist.nhf"):
                    names += [f"{node.module}.{a.name}" for a in node.names]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            for name in names:
                if name in retired:
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)}:{node.lineno} -> {name}"
                    )
    assert offenders == [], "retired paths still imported:\n" + "\n".join(offenders)
