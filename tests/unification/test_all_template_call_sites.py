"""Keyword-check every workflow-template call against the resolved signature.

`test_nhm_notebook_signatures.py` builds its registry by walking
`assist.common.*`, so a helper that has NOT been unified yet -- `map_template`,
`display_controls` -- has zero call-site coverage there. That gap hid three real
breaks in nhm templates until the notebooks were finally executed:

  * `make_hf_map(poi_id_sel=...)`        -> notebook 2, TypeError
  * `make_streamflow_map(poi_id_sel=...)` -> notebook 6, TypeError
  * `import assist.nhm.display_controls`  -> notebook 5, ModuleNotFoundError

This module resolves calls against *every* `assist.*` module, unified or not.

It also avoids the two things `Signature.bind_partial` cannot do: it reports
ALL unexpected keywords rather than only the first, and it detects required
parameters that were never supplied (`bind_partial` permits those by design).
"""
import ast
import importlib
import inspect
import pathlib

import pytest

from tests.unification.harness import REPO_ROOT

def _parses(path: pathlib.Path) -> bool:
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return False
    return True


ALL_TEMPLATES = sorted(
    p for p in (REPO_ROOT / "src/workflow_templates").rglob("*.py")
    if ".ipynb_checkpoints" not in str(p)
)

# Two nhf helper templates are not valid Python and have not been since
# c75158d ("Jupytext fix") -- a bad round-trip pasted cell *output* into the
# source (`<...PrmsParameters object at 0x...>`, `mappingproxy({...})`) and
# broke the indentation of another. They cannot be parsed, so they cannot be
# checked; they are listed here so that this stays a known, recorded fact and
# a *newly* unparseable template still fails the test below.
KNOWN_UNPARSEABLE = {
    "src/workflow_templates/nhf/create_upland_lowland_breaks.py",
    "src/workflow_templates/nhf/make_param_file.py",
}

TEMPLATES = [p for p in ALL_TEMPLATES if _parses(p)]


def test_no_new_unparseable_templates():
    """Guards the KNOWN_UNPARSEABLE list above from silently growing."""
    broken = {
        str(p.relative_to(REPO_ROOT)) for p in ALL_TEMPLATES if not _parses(p)
    }
    assert broken == KNOWN_UNPARSEABLE, (
        f"newly unparseable: {sorted(broken - KNOWN_UNPARSEABLE)}; "
        f"newly fixed (remove from KNOWN_UNPARSEABLE): "
        f"{sorted(KNOWN_UNPARSEABLE - broken)}"
    )

POSITIONAL_KINDS = (
    inspect.Parameter.POSITIONAL_ONLY,
    inspect.Parameter.POSITIONAL_OR_KEYWORD,
)


def _imported_functions(tree):
    """Map local name -> (module, attr, function) for `from assist.X import ...`."""
    found = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ImportFrom) and node.module):
            continue
        if not node.module.startswith("assist."):
            continue
        module = importlib.import_module(node.module)
        for alias in node.names:
            obj = getattr(module, alias.name, None)
            if inspect.isfunction(obj):
                found[alias.asname or alias.name] = (node.module, alias.name, obj)
    return found


def _check_call(node, entry):
    modname, fname, fn = entry
    params = inspect.signature(fn).parameters
    has_kwargs = any(p.kind is p.VAR_KEYWORD for p in params.values())
    has_varargs = any(p.kind is p.VAR_POSITIONAL for p in params.values())

    supplied = {kw.arg for kw in node.keywords if kw.arg is not None}
    splatted = any(kw.arg is None for kw in node.keywords)
    problems = []

    if not has_kwargs:
        # every unexpected keyword, not just the first one bind_partial trips on
        unexpected = sorted(supplied - set(params))
        if unexpected:
            problems.append(f"unexpected keyword(s) {unexpected}")

    if not splatted and not has_varargs:
        filled = set(supplied)
        pos_names = [n for n, p in params.items() if p.kind in POSITIONAL_KINDS]
        filled |= set(pos_names[: len(node.args)])
        missing = [
            n
            for n, p in params.items()
            if p.default is inspect.Parameter.empty
            and p.kind not in (p.VAR_KEYWORD, p.VAR_POSITIONAL)
            and n not in filled
        ]
        if missing:
            # bind_partial cannot see these at all
            problems.append(f"missing required arg(s) {missing}")

    return [f"{modname}.{fname}: {p}" for p in problems]


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.name)
def test_every_call_matches_its_signature(template):
    tree = ast.parse(template.read_text(encoding="utf-8"))
    imported = _imported_functions(tree)

    failures = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        entry = imported.get(node.func.id)
        if entry is None:
            continue
        for problem in _check_call(node, entry):
            failures.append(f"  line {node.lineno}: {problem}")

    assert not failures, (
        f"{template.relative_to(REPO_ROOT)} calls helpers incorrectly:\n"
        + "\n".join(failures)
    )


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.name)
def test_every_assist_module_import_resolves(template):
    """`assist.nhm.display_controls` was deleted while two templates kept
    importing it, so notebook 5 died with ModuleNotFoundError."""
    tree = ast.parse(template.read_text(encoding="utf-8"))
    missing = []
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        elif isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        for name in names:
            if not name.startswith("assist."):
                continue
            try:
                importlib.import_module(name)
            except Exception as exc:
                missing.append(f"  line {node.lineno}: {name} -> {exc}")

    assert not missing, (
        f"{template.relative_to(REPO_ROOT)} imports modules that do not "
        f"import:\n" + "\n".join(missing)
    )
