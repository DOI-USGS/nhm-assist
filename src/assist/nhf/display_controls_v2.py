"""Shim: the implementation now lives in `assist.common.display_controls`.

Concern 5 of the helper unification. This is the one module where the *nhm*
side won rather than nhf (spec decision 8's default): the two versions held
the same nine functions, but nhm's had been hardened since the fork with
`_require_state` guards, output-directory creation, `None`-checks around POI
selection, and batch-mode-safe artifact reporting. nhf's copy had none of
that, so taking nhf's side would have been a straight regression.

The one thing nhf's copy did differently -- omitting `HW_basins` /
`HW_basins_gdf`, which are GFv1.1-only and absent from `map_template_v2` -- is
preserved in the unified module by asking the injected map backend which
keywords it accepts (`_accepted_by` / `_supported`), so one module drives both
fabrics.

This module is aliased rather than re-exported: `display_controls` carries
mutable module-level state that notebooks assign (`dc.hru_gdf = hru_gdf`,
`dc.make_var_map = make_var_map`). A `from ... import *` shim would copy those
names into this namespace, and assignments here would never reach the
implementation's globals. Rebinding `sys.modules` makes
`import assist.nhf.display_controls_v2 as dc` hand back the real module.
"""
import sys

from assist.common import display_controls as _impl

sys.modules[__name__] = _impl
