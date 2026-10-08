"""Adding POIs to a parameter file must not depend on the `nobs` dimension.

pyPRMS's `Parameters.add_poi` updates the global dimensions `npoigages` and
`nobs` together and looks both up unconditionally::

    for cdim in ('npoigages', 'nobs'):
        self.dimensions.get(cdim).size = len(poi_gage_id)

`Dimensions.get` raises on a dimension that is not declared, so any parameter
file without `nobs` fails before anything is written. Bandit-written GFv1.1
files carry `nobs == npoigages`; the GFv2-derived pyPRMS subsetter emits no
`nobs` at all, so `add_pois_to_parameters` failed on every v1.2 and v2
subdomain with `ValueError: Dimension, nobs, does not exist.`

These run against the parameter files the repo already ships, which cover both
shapes: Walla_Walla is Bandit-written and declares `nobs`, while WWGW_Basin,
UmatillaRiver and Rogue_River are "Written by pyPRMS / GFv2 derived" and do
not.
"""
from __future__ import annotations

import pathlib as pl
import shutil

import pandas as pd
import pytest

from tests.unification.harness import MODELS

# model -> whether its shipped parameter file declares a `nobs` dimension
PARAM_FILES = {
    "walla_walla": True,
    "wwgw_basin": False,
    "umatilla": False,
}


def _declared_dimensions(param_file: pl.Path) -> dict[str, int]:
    """Global dimension name -> size, read out of a PRMS parameter file."""
    lines = param_file.read_text(encoding="utf-8").splitlines()
    start = lines.index("** Dimensions **") + 1
    try:
        end = lines.index("** Parameters **")
    except ValueError:
        end = len(lines)
    entries = [ll.strip() for ll in lines[start:end] if ll.strip() and not ll.startswith("####")]
    return {name: int(size) for name, size in zip(entries[0::2], entries[1::2])}


def _model_param_file(model: str) -> pl.Path:
    param_file = pl.Path(MODELS[model]) / "myparam.param"
    if not param_file.exists():
        pytest.skip(f"{model} parameter file not present in this checkout")
    return param_file


def _stage_model(tmp_path: pl.Path, model: str) -> tuple[pl.Path, pl.Path]:
    """Copy one model's parameter file into `tmp_path` and write the POI csv.

    The csv is the handoff `create_append_gages_to_param_file` leaves behind:
    a `poi_gage_id` and the `nhm_seg` it was matched to. A segment that is not
    already a POI is chosen so the append path is the one exercised, rather
    than the replace-an-existing-POI path.
    """
    from pyPRMS import ParameterFile
    from pyPRMS.metadata.metadata import MetaData

    source = _model_param_file(model)
    staged = tmp_path / "myparam.param"
    shutil.copy(source, staged)

    pdb = ParameterFile(str(staged), metadata=MetaData().metadata, verbose=False)
    taken = set(pdb.get("poi_gage_segment").tolist())
    free = [
        seg for seg, idx0 in sorted(pdb.get("nhm_seg").index_map.items())
        if idx0 + 1 not in taken
    ]
    assert free, f"{model}: every segment is already a POI, cannot test the append path"

    pd.DataFrame({"poi_gage_id": ["99999999"], "nhm_seg": [free[0]]}).to_csv(
        tmp_path / "append_gages_to_param_file.csv", index=False
    )
    return staged, tmp_path


@pytest.mark.parametrize("model", sorted(PARAM_FILES))
def test_add_pois_works_whether_or_not_nobs_is_declared(tmp_path, model):
    """The v1.2/v2 `ValueError: Dimension, nobs, does not exist.` regression."""
    from assist.common.assist_utilities import make_myparam_addl_gages_param_file

    staged, model_dir = _stage_model(tmp_path, model)
    before = _declared_dimensions(staged)
    assert before.get("nobs") is not None if PARAM_FILES[model] else "nobs" not in before

    make_myparam_addl_gages_param_file(
        model_dir=model_dir, param_filename=str(staged)
    )

    written = model_dir / "myparam_addl_gages.param"
    assert written.exists(), f"{model}: no new parameter file was written"
    after = _declared_dimensions(written)
    assert after["npoigages"] == before["npoigages"] + 1, (
        f"{model}: the appended POI did not reach npoigages"
    )
    assert after["nobs"] == after["npoigages"], (
        f"{model}: nobs must track npoigages, the NHM convention Bandit files "
        f"already follow (got nobs={after.get('nobs')})"
    )


def test_nobs_is_seeded_from_npoigages_not_invented():
    """The seeded size matches the POI count, so PRMS sees a coherent file."""
    import inspect

    from assist.common.assist_utilities import make_myparam_addl_gages_param_file

    source = inspect.getsource(make_myparam_addl_gages_param_file)
    assert 'exists("nobs")' in source, (
        "the nobs guard is gone; pyPRMS add_poi will raise again on any "
        "GFv2-derived parameter file"
    )
    assert 'get("npoigages").size' in source, (
        "nobs should be seeded from npoigages, matching Bandit-written files"
    )
