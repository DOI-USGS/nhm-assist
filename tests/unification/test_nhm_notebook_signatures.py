"""Signature-binding sweep over every workflow template call site.

The unification consolidated the per-baseline hydrofabric/streamflow/output
helpers into keyword-only, no-default functions under `assist.common.*`.
Nothing checked that every workflow-template call site was kept in sync with
those signatures. An earlier, narrower version of this test only checked
notebook 1 (`1_create_streamflow_observations.py`) of the nhm/nhf workflows
against three named functions — which is exactly why ten other call sites
(seven passing the retired `nwis_gages_file=` keyword, three unpacking the
wrong number of values from `make_hf_map_elements`) went undetected.

This version sweeps every `.py` file under `src/workflow_templates/` and,
for every call to any public function that traces back to `assist.common.*`
(reached directly or through one of the per-baseline compatibility shims,
e.g. `assist.nhm.nhm_hydrofabric` / `assist.nhf.nhm_hydrofabric_v2`, which
just re-export the `assist.common` implementation — see the module
docstrings in those shim files), it asserts two things:

  1. Every keyword argument passed at the call site is accepted by the
     function's real signature (`inspect.signature(...).bind_partial`).
     This is the check that would have caught `nwis_gages_file=`.
  2. Where the call site tuple-unpacks the result (`a, b, c = f(...)`), the
     number of unpacked targets matches the function's actual return arity,
     inferred statically from its own `return` statements. A single-name
     assignment (`x = f(...)`) is always legal Python regardless of how many
     values `f` returns, so it is never reported here — only a mismatched
     *tuple*-unpack count is. This is the check that would have caught the
     `make_hf_map_elements` 10-vs-12 drift.

Everything is parsed with `ast`, not regex or import side effects, so the
test survives call sites moving to different lines and does not need to
execute any notebook cell.

Two files are skipped by name: they are not valid, parseable Python at all,
independent of anything this concern touches, and are out of scope to fix
here:
  - `nhf/create_upland_lowland_breaks.py` (IndentationError at parse time)
  - `nhf/make_param_file.py` (contains a pasted Python object repr, not code)
"""
from __future__ import annotations

import ast
import importlib
import inspect
import pathlib as pl
import pkgutil
import textwrap

import pytest

REPO_ROOT = pl.Path(__file__).resolve().parents[2]
TEMPLATES_ROOT = REPO_ROOT / "src/workflow_templates"

# Name -> reason skipped. Both are pre-existing, unrelated syntax problems;
# `ast.parse` cannot even build a tree for them.
SKIP_FILES = {
    "create_upland_lowland_breaks.py": "IndentationError at parse time (pre-existing)",
    "make_param_file.py": "contains a pasted Python object repr, not valid code (pre-existing)",
}


def _iter_template_files():
    for path in sorted(TEMPLATES_ROOT.rglob("*.py")):
        if path.name in SKIP_FILES:
            continue
        yield path


def _common_function_registry() -> dict[str, object]:
    """Every public, top-level function actually defined somewhere under
    `assist.common.*` (not merely re-exported into it), keyed by name.

    Filtering on `obj.__module__ == modname` means a function imported into
    one common module from another (e.g. `hydrofabric.py` importing
    `make_HW_cal_level_files` from `assist_utilities.py`) is only counted
    once, at its true home module.
    """
    import assist.common as common_pkg

    registry: dict[str, object] = {}
    for modinfo in pkgutil.iter_modules(common_pkg.__path__):
        modname = f"assist.common.{modinfo.name}"
        module = importlib.import_module(modname)
        for name, obj in vars(module).items():
            if name.startswith("_") or not inspect.isfunction(obj):
                continue
            if obj.__module__ != modname:
                continue
            registry[name] = obj
    return registry


def _own_return_nodes(func_node: ast.FunctionDef) -> list[ast.Return]:
    """Every `return` statement that belongs to `func_node` itself, not to a
    nested `def`/`lambda` inside it."""
    returns: list[ast.Return] = []

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if isinstance(child, ast.Return):
                returns.append(child)
            visit(child)

    visit(func_node)
    return returns


def _return_arity(fn) -> int | None:
    """Number of values `fn` returns, inferred statically from its own
    `return` statements.

    Returns `None` (meaning: skip the arity check for this function) when
    that can't be determined reliably from source alone — e.g. the function
    has no `return` with a value, or its `return` statements disagree on
    shape (a literal tuple in one branch, a bare name in another). Guessing
    wrong there would produce false-positive failures unrelated to the two
    break classes this test targets.
    """
    try:
        source = inspect.getsource(fn)
    except (OSError, TypeError):
        return None
    try:
        func_node = ast.parse(textwrap.dedent(source)).body[0]
    except SyntaxError:
        return None

    arities = set()
    for ret in _own_return_nodes(func_node):
        if ret.value is None:
            continue
        if isinstance(ret.value, (ast.Tuple, ast.List)):
            arities.add(len(ret.value.elts))
        else:
            arities.add(1)

    if len(arities) == 1:
        return arities.pop()
    return None


def _module_level_bound_names(tree: ast.Module) -> set[str]:
    """Names this file itself defines or assigns at any scope: a `def`, a
    `class`, or a plain assignment target.

    Used to keep a name imported from `assist.common` (through a shim) out
    of consideration if the same file later gives that name a local,
    unrelated meaning — e.g. `nhf/Fetch_poi_supplimental_information.py`
    defines its own top-level `find_missing_gage_info`/
    `fetch_ref_npoigages_info`/`fetch_non_ref_npoigages_info` rather than
    using the `assist.common` versions of those names. None of those three
    are actually imported from `assist.common` in that file either, so this
    guard is currently a no-op safety net rather than something observed to
    bite — but a shadowed import would otherwise silently mis-attribute
    calls to the wrong function.
    """
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bound.add(target.id)
    return bound


def _imported_common_functions(tree: ast.Module, registry: dict[str, object]) -> dict[str, object]:
    """Map each locally-bound name in this file's `ast.ImportFrom` statements
    to the actual `assist.common.*` function object it resolves to, for
    names that (a) come from some `assist.*` module (directly from
    `assist.common`, or through one of the per-baseline compatibility shims)
    and (b) resolve, by identity, to a function in `registry`.

    Only plain `from assist.x.y import name[, name2, ...]` / `... import name
    as alias` statements are considered — matching how every call site in
    this codebase actually imports these helpers (no `import x.y as z`
    module-alias + attribute-call usage was found in a survey of
    `src/workflow_templates/`).
    """
    registry_ids = {id(fn) for fn in registry.values()}
    shadowed = _module_level_bound_names(tree)

    bound: dict[str, object] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if not node.module.startswith("assist."):
            continue
        try:
            module = importlib.import_module(node.module)
        except Exception:
            # A handful of shim/leaf modules pull in optional, environment-
            # specific dependencies. A template that fails to import here
            # would also fail to import at runtime, which is a different
            # concern than the one this test targets.
            continue
        for alias in node.names:
            try:
                obj = getattr(module, alias.name)
            except AttributeError:
                continue
            if not inspect.isfunction(obj) or id(obj) not in registry_ids:
                continue
            local_name = alias.asname or alias.name
            bound[local_name] = obj

    return {name: fn for name, fn in bound.items() if name not in shadowed}


def _iter_calls(tree: ast.Module):
    """Every bare `name(...)` call anywhere in `tree` (not `obj.name(...)`)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            yield node


def _iter_assign_calls(tree: ast.Module):
    """(assignment target, call) for every assignment whose RHS is a bare
    `name(...)` call: `x = f(...)` or `a, b = f(...)`."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        call = node.value
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
            for target in node.targets:
                yield target, call


def test_sweep_covers_every_template_file():
    """Guard against the sweep silently covering nothing (e.g. a path typo)."""
    files = list(_iter_template_files())
    assert len(files) > 50, (
        f"expected the sweep to find well over 50 template files under "
        f"{TEMPLATES_ROOT}, found {len(files)}. Either the templates moved "
        "or this test's glob needs updating."
    )
    names = {p.name for p in files}
    for skipped in SKIP_FILES:
        assert skipped not in names, f"{skipped} should have been filtered out"


def test_every_call_site_binds_and_unpacks_correctly():
    registry = _common_function_registry()
    assert registry, "expected at least one public function under assist.common.*"

    keyword_failures: list[str] = []
    arity_mismatches: list[str] = []
    checked_calls = 0
    checked_files = 0

    for path in _iter_template_files():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)  # pre-filtered above to files that parse cleanly
        bound = _imported_common_functions(tree, registry)
        if not bound:
            continue
        checked_files += 1

        for call in _iter_calls(tree):
            fn = bound.get(call.func.id)
            if fn is None:
                continue
            if any(kw.arg is None for kw in call.keywords) or any(
                isinstance(a, ast.Starred) for a in call.args
            ):
                # A **kwargs/*args expansion can't be verified statically;
                # not the class of bug this test targets.
                continue

            checked_calls += 1
            sig = inspect.signature(fn)
            dummy_kwargs = {kw.arg: None for kw in call.keywords}
            try:
                sig.bind_partial(*([None] * len(call.args)), **dummy_kwargs)
            except TypeError as exc:
                keyword_failures.append(
                    f"{path.relative_to(REPO_ROOT)}:{call.lineno} calls "
                    f"{call.func.id}(...) with arguments that don't match "
                    f"its signature {sig}: {exc}"
                )

        for target, call in _iter_assign_calls(tree):
            if not isinstance(target, (ast.Tuple, ast.List)):
                continue  # single-name assignment is always legal; not our concern
            fn = bound.get(call.func.id)
            if fn is None:
                continue
            expected = _return_arity(fn)
            if expected is None:
                continue
            actual = len(target.elts)
            if actual != expected:
                arity_mismatches.append(
                    f"{path.relative_to(REPO_ROOT)}:{call.lineno} unpacks "
                    f"{actual} value(s) from {call.func.id}(...), expected "
                    f"{expected}"
                )

    assert checked_files > 0, (
        "expected at least one template file to import something from "
        "assist.common.*; found none. Either every call site was removed "
        "or this test's import resolution needs updating."
    )
    assert checked_calls > 0, (
        "expected at least one checkable call site (with only plain "
        "keyword/positional arguments); found none."
    )
    assert keyword_failures == [], "\n".join(keyword_failures)
    assert arity_mismatches == [], "\n".join(arity_mismatches)
