"""Compatibility shim. Implementation lives in assist.common.streamflow_postprocess.

This module had no nhf counterpart, so it was never part of the nine-pair
helper unification. It moved anyway once the workflow templates were shared:
`common/4_run_model_using_pywatershed.py` was importing it, which left a shared
template reaching into a per-fabric package.

Moved with a plain `git mv` rather than the two-commit pattern used for the
other modules: 28 lines over two same-day commits by one author, so there is no
multi-author provenance for `git blame` to lose.
"""
from assist.common.streamflow_postprocess import subset_seg_outflow_to_poi_gages

__all__ = ["subset_seg_outflow_to_poi_gages"]
