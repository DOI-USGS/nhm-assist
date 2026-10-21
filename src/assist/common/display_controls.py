import inspect
from pathlib import Path

from ipywidgets import widgets
from IPython.display import HTML, clear_output, display
from assist.common.output_visualization import retrieve_hru_output_info
from ipywidgets import VBox
from assist.common.output_plots import plot_colors
from assist.common.output_plots import (
    var_colors_dict,
    leg_only_dict,
    make_plot_var_for_hrus_in_poi_basin,
    oopla,
)
from assist.common.output_plots import create_streamflow_plot

# The map backend used to be a module-level `None` for the consuming notebook
# to inject, so this module could stay agnostic to the diverged nhm/nhf
# map_template implementations. Those are unified into one
# assist.common.map_template, so there is nothing left to be agnostic about,
# and the placeholder was actively harmful: only the deleted nhf
# display_controls_v2 ever assigned it, so on the nhm side `generate_map`
# reached `make_var_map(...)` with None and raised
# `TypeError: 'NoneType' object is not callable` the moment the button was
# clicked. Importing it directly makes that unrepresentable. Tests that
# exercise an alternate backend still override these names on the module.
from assist.common.map_template import (
    make_hf_map,
    make_par_map,
    make_streamflow_map,
    make_var_map,
)

root_dir = None
out_dir = None
plot_start_date = None
plot_end_date = None
water_years = None
hru_gdf = None
poi_df = None
seg_gdf = None
html_maps_dir = None
html_plots_dir = None
Folium_maps_dir = None
year_list = None
subdomain = None
param_filename = None
output_var_list = None
output_netcdf_filename = None
HW_basins = None
HW_basins_gdf = None
v = None
yr = None
v2 = None
plot_checks = None
btn_generate = None
cb_map = None
cb_summary = None
cb_flux = None
out_map = None
out_summary = None
out_flux = None
gage_txt = None
map_out = None
plot_out = None
waterdata_gages_aoi = None
gages_df = None
model_dir = None
hf_map_out = None
nhru_params = None
par_dd = None
mo_dd = None
par_map_out = None
overview_map_out = None

# import pathlib as pl
# import os
# root_dir = pl.Path(os.getcwd().rsplit("nhm-assist", 1)[0] + "nhm-assist")

def warn(msg: str):
    """Display a bold red warning in the notebook."""
    display(HTML(f"<div style='color:#b00020; font-weight:600'>{msg}</div>"))


def _show_loading(kind: str) -> None:
    """Display a note that the `kind` is being generated."""
    display(
        HTML(
            f"<div style='color:#6b7280; font-style:italic'>"
            f"Generating the {kind}… this can take a minute.</div>"
        )
    )


def _report_external_artifact(kind: str, artifact) -> None:
    """Report the generated external artifact without embedding a preview."""
    path = None if artifact is None else Path(artifact).resolve()
    if path is None:
        msg = f"Generated the {kind} and requested it open in an external browser."
    else:
        msg = (
            f"Generated the {kind} and requested it open in an external browser."
            f"<br><code>{path}</code>"
        )
    display(HTML(f"<div style='color:#1f2937'>{msg}</div>"))


def _accepted_by(fn, *names: str) -> list:
    """Return those `names` that `fn` actually accepts as keywords.

    Headwater basins are a GFv1.1 concept: nhm's map_template takes
    HW_basins/HW_basins_gdf, nhf's map_template_v2 has no such parameters and
    its notebooks never set that state. Asking the injected backend what it
    accepts lets this one module drive both sides.
    """
    if fn is None:
        return []
    params = inspect.signature(fn).parameters
    if any(p.kind is p.VAR_KEYWORD for p in params.values()):
        return list(names)
    return [name for name in names if name in params]


# NOTE: HW_basins/HW_basins_gdf are deliberately absent from every
# _require_state list. Since concern 4 the unified map_template advertises them
# on all four map builders (defaulted to None) and guards each render on
# `is not None`, so a GFv2 notebook that never sets them is correct, not broken.
def _supported(fn, **kwargs) -> dict:
    """Drop the kwargs `fn` does not accept (see `_accepted_by`)."""
    keep = set(_accepted_by(fn, *kwargs))
    return {k: v for k, v in kwargs.items() if k in keep}


def _require_state(*names: str) -> bool:
    missing = [name for name in names if globals().get(name) is None]
    if missing:
        warn(
            "Notebook controls are not initialized. Re-run the widget setup cell. "
            f"Missing: {', '.join(missing)}"
        )
        return False
    return True


def _ensure_output_dirs() -> None:
    for name in ("html_maps_dir", "html_plots_dir", "Folium_maps_dir"):
        path = globals().get(name)
        if path is not None:
            Path(path).mkdir(parents=True, exist_ok=True)


def _get_valid_poi() -> str:
    """
    Return a valid POI identifier: the combobox value if valid,
    otherwise the first available POI from poi_df.
    """
    if not _require_state("poi_df", "v2"):
        return None
    ids = poi_df.poi_gage_id.values
    return v2.value if v2.value in ids else ids[0]


def generate_map() -> None:
    """
    Generate and display the Folium map for the selected variable, year, and POI.
    """
    if not _require_state(
        "root_dir",
        "out_dir",
        "plot_start_date",
        "plot_end_date",
        "water_years",
        "hru_gdf",
        "poi_df",
        "seg_gdf",
        "html_maps_dir",
        "year_list",
        "yr",
        "Folium_maps_dir",
        "subdomain",
        "v",
        "v2",
    ):
        return
    _ensure_output_dirs()
    # With no gage selected, pass None so the map opens at the full model
    # extent instead of zooming to a fallback gage.
    poi_gage_id = v2.value if v2.value in poi_df.poi_gage_id.values else None
    map_file = make_var_map(
        **_supported(
            make_var_map,
            root_dir=root_dir,
            out_dir=out_dir,
            output_var_sel=v.value,
            plot_start_date=plot_start_date,
            plot_end_date=plot_end_date,
            water_years=water_years,
            hru_gdf=hru_gdf,
            poi_df=poi_df,
            poi_gage_id_sel=poi_gage_id,
            seg_gdf=seg_gdf,
            html_maps_dir=html_maps_dir,
            year_list=year_list,
            sel_year=yr.value,
            Folium_maps_dir=Folium_maps_dir,
            HW_basins=HW_basins,
            subdomain=subdomain,
        )
    )
    _report_external_artifact("map", map_file)


def generate_summary() -> None:
    """
    Generate and display the summary time-series plot of HRU contributions
    for the selected variable and POI.
    """
    if not _require_state(
        "out_dir",
        "param_filename",
        "water_years",
        "hru_gdf",
        "poi_df",
        "v",
        "plot_start_date",
        "plot_end_date",
        "subdomain",
        "html_plots_dir",
    ):
        return
    _ensure_output_dirs()
    poi_gage_id = _get_valid_poi()
    if poi_gage_id is None:
        return
    plot_file = make_plot_var_for_hrus_in_poi_basin(
        out_dir=out_dir,
        param_filename=param_filename,
        water_years=water_years,
        hru_gdf=hru_gdf,
        poi_df=poi_df,
        output_var_sel=v.value,
        poi_gage_id_sel=poi_gage_id,
        plot_start_date=plot_start_date,
        plot_end_date=plot_end_date,
        plot_colors=plot_colors,
        subdomain=subdomain,
        html_plots_dir=html_plots_dir,
    )
    _report_external_artifact("plot", plot_file)


def generate_flux() -> None:
    """
    Generate and display the flux rates time-series plot for the selected
    variable and POI.
    """
    if not _require_state(
        "out_dir",
        "param_filename",
        "water_years",
        "hru_gdf",
        "poi_df",
        "output_var_list",
        "v",
        "plot_start_date",
        "plot_end_date",
        "subdomain",
        "html_plots_dir",
    ):
        return
    _ensure_output_dirs()
    poi_gage_id = _get_valid_poi()
    if poi_gage_id is None:
        return
    plot_file = oopla(
        out_dir=out_dir,
        param_filename=param_filename,
        water_years=water_years,
        hru_gdf=hru_gdf,
        poi_df=poi_df,
        output_var_list=output_var_list,
        output_var_sel=v.value,
        poi_gage_id_sel=poi_gage_id,
        plot_start_date=plot_start_date,
        plot_end_date=plot_end_date,
        plot_colors=plot_colors,
        var_colors_dict=var_colors_dict,
        leg_only_dict=leg_only_dict,
        subdomain=subdomain,
        html_plots_dir=html_plots_dir,
    )
    _report_external_artifact("plot", plot_file)


def on_generate_clicked(b: widgets.Button) -> None:
    """
    When the Generate button is clicked, clear all outputs and
    create only the selected plots.
    """
    if not _require_state(
        "v",
        "yr",
        "v2",
        "plot_checks",
        "btn_generate",
        "out_map",
        "out_summary",
        "out_flux",
        "cb_map",
        "cb_summary",
        "cb_flux",
    ):
        return
    # Clear every output area, not just the selected ones, so results from a
    # plot type that is now unchecked do not linger from a previous click.
    for out in (out_map, out_summary, out_flux):
        out.clear_output()

    # Plots can take a while to build, so show the user that work is underway.
    btn_description = btn_generate.description
    btn_generate.disabled = True
    btn_generate.description = "Generating…"
    try:
        # Map
        if cb_map.value:
            with out_map:
                _show_loading("map")
                generate_map()

        # Summary TS
        if cb_summary.value:
            with out_summary:
                _show_loading("summary time-series plot")
                generate_summary()

        # Flux TS
        if cb_flux.value:
            with out_flux:
                _show_loading("flux time-series plot")
                generate_flux()
    finally:
        btn_generate.description = btn_description
        btn_generate.disabled = not (cb_map.value or cb_summary.value or cb_flux.value)


def _get_valid_poi1() -> str:
    """
    Return a valid POI identifier: the text‐input value if valid,
    otherwise the first available POI from poi_df.
    """
    if not _require_state("poi_df", "gage_txt"):
        return None
    # Keep parameter-file order; a set has no stable order, so its "first"
    # gage could change between kernel sessions.
    ids = list(poi_df.poi_gage_id.values)
    raw = gage_txt.value.strip()
    return raw if raw in ids else ids[0]

def on_map_clicked(b: widgets.Button) -> None:
    """
    When clicked, clear previous map, default to first POI if none entered,
    then generate and display the streamflow map.
    """
    if not _require_state(
        "map_out",
        "root_dir",
        "out_dir",
        "plot_start_date",
        "plot_end_date",
        "water_years",
        "hru_gdf",
        "poi_df",
        "seg_gdf",
        "html_maps_dir",
        "subdomain",
        "output_netcdf_filename",
        "gage_txt",
    ):
        return
    _ensure_output_dirs()
    # The plot and map share one set of controls, so clear the plot's output
    # too; otherwise a stale plot message lingers above the new map.
    if plot_out is not None:
        plot_out.clear_output()
    with map_out:
        clear_output()
        # With no gage selected, pass None so the map opens at the full model
        # extent instead of zooming to a fallback gage.
        raw = gage_txt.value.strip()
        poi_gage_id_sel = raw if raw in set(poi_df.poi_gage_id.values) else None

        _show_loading("streamflow map")
        try:
            map_file = make_streamflow_map(
                **_supported(
                    make_streamflow_map,
                    root_dir=root_dir,
                    out_dir=out_dir,
                    plot_start_date=plot_start_date,
                    plot_end_date=plot_end_date,
                    water_years=water_years,
                    hru_gdf=hru_gdf,
                    poi_df=poi_df,
                    poi_gage_id_sel=poi_gage_id_sel,
                    seg_gdf=seg_gdf,
                    html_maps_dir=html_maps_dir,
                    subdomain=subdomain,
                    HW_basins_gdf=HW_basins_gdf,
                    HW_basins=HW_basins,
                    output_netcdf_filename=output_netcdf_filename,
                )
            )
            _report_external_artifact("map", map_file)

        except (KeyError, IndexError):
            warn(
                f"The POI or streamgage ID “{poi_gage_id_sel}” is not in the dataset. "
                "Please check the ID and try again."
            )
        except Exception as e:
            warn(f"Unexpected error while generating the map: {e}")

def on_plot_clicked(b: widgets.Button) -> None:
    """
    When clicked, clear previous plot, default to first POI if none entered,
    then generate and display the streamflow plot.
    """
    if not _require_state(
        "plot_out",
        "gage_txt",
        "poi_df",
        "plot_start_date",
        "plot_end_date",
        "water_years",
        "html_plots_dir",
        "output_netcdf_filename",
        "out_dir",
        "subdomain",
    ):
        return
    _ensure_output_dirs()
    # The plot and map share one set of controls, so clear the map's output
    # too; otherwise a stale map message lingers below the new plot.
    if map_out is not None:
        map_out.clear_output()
    with plot_out:
        clear_output()
        poi_gage_id_sel = _get_valid_poi1()
        if poi_gage_id_sel is None:
            return

        _show_loading("streamflow plot")
        try:
            fplot = create_streamflow_plot(
                poi_gage_id_sel=poi_gage_id_sel,
                plot_start_date=plot_start_date,
                plot_end_date=plot_end_date,
                water_years=water_years,
                html_plots_dir=html_plots_dir,
                output_netcdf_filename=output_netcdf_filename,
                out_dir=out_dir,
                subdomain=subdomain,
            )
            # None means the gage had no observations to plot; the reason was
            # already printed, so there is nothing to report.
            if fplot is not None:
                _report_external_artifact("plot", fplot)

        except (KeyError, IndexError):
            warn(
                f"The streamgage ID “{poi_gage_id_sel}” is not in the dataset. "
                "Please check the ID and try again."
            )
        except Exception as e:
            warn(f"Unexpected error while generating the plot: {e}")


def on_hf_map_clicked(b: widgets.Button) -> None:
    """
    When clicked, clear the previous message, then generate the hydrofabric
    map and open it in a browser.
    """
    if not _require_state(
        "hf_map_out",
        "root_dir",
        "hru_gdf",
        "poi_df",
        "seg_gdf",
        "waterdata_gages_aoi",
        "gages_df",
        "html_maps_dir",
        "Folium_maps_dir",
        "param_filename",
        "subdomain",
    ):
        return
    _ensure_output_dirs()
    with hf_map_out:
        clear_output()
        try:
            map_file = make_hf_map(
                root_dir=root_dir,
                hru_gdf=hru_gdf,
                HW_basins_gdf=HW_basins_gdf,
                HW_basins=HW_basins,
                poi_df=poi_df,
                poi_gage_id_sel="",
                seg_gdf=seg_gdf,
                waterdata_gages_aoi=waterdata_gages_aoi,
                gages_df=gages_df,
                html_maps_dir=html_maps_dir,
                Folium_maps_dir=Folium_maps_dir,
                param_filename=param_filename,
                subdomain=subdomain,
                model_dir=model_dir,
            )
            _report_external_artifact("map", map_file)

        except Exception as e:
            warn(f"Unexpected error while generating the map: {e}")


def on_par_map_clicked(b: widgets.Button) -> None:
    """
    When clicked, clear the previous message, then generate the parameter map
    for the selected parameter (and month, if the parameter is monthly) and
    open it in a browser.
    """
    if not _require_state(
        "par_map_out",
        "par_dd",
        "mo_dd",
        "root_dir",
        "hru_gdf",
        "poi_df",
        "nhru_params",
        "Folium_maps_dir",
        "seg_gdf",
        "html_maps_dir",
        "param_filename",
        "subdomain",
    ):
        return
    _ensure_output_dirs()
    with par_map_out:
        clear_output()
        # The notebook disables the month dropdown for parameters that are
        # dimensioned by HRU only; make_par_map expects mo_sel=None for those.
        mo_sel = None if mo_dd.disabled else mo_dd.index + 1
        try:
            map_file = make_par_map(
                root_dir=root_dir,
                hru_gdf=hru_gdf,
                HW_basins=HW_basins,
                poi_df=poi_df,
                par_sel=par_dd.value,
                mo_sel=mo_sel,
                mo_name=mo_dd.value,
                nhru_params=nhru_params,
                Folium_maps_dir=Folium_maps_dir,
                seg_gdf=seg_gdf,
                html_maps_dir=html_maps_dir,
                param_filename=param_filename,
                subdomain=subdomain,
            )
            _report_external_artifact("map", map_file)

        except Exception as e:
            warn(f"Unexpected error while generating the map: {e}")


def on_overview_map_clicked(b: widgets.Button) -> None:
    """
    When clicked, clear the previous message, then generate the streamflow
    map for the whole subdomain (not zoomed to a gage) and open it in a
    browser.
    """
    if not _require_state(
        "overview_map_out",
        "root_dir",
        "out_dir",
        "plot_start_date",
        "plot_end_date",
        "water_years",
        "hru_gdf",
        "poi_df",
        "seg_gdf",
        "html_maps_dir",
        "subdomain",
        "output_netcdf_filename",
    ):
        return
    _ensure_output_dirs()
    with overview_map_out:
        clear_output()
        _show_loading("streamflow map")
        try:
            map_file = make_streamflow_map(
                **_supported(
                    make_streamflow_map,
                    root_dir=root_dir,
                    out_dir=out_dir,
                    plot_start_date=plot_start_date,
                    plot_end_date=plot_end_date,
                    water_years=water_years,
                    hru_gdf=hru_gdf,
                    poi_df=poi_df,
                    poi_gage_id_sel=None,
                    seg_gdf=seg_gdf,
                    html_maps_dir=html_maps_dir,
                    subdomain=subdomain,
                    HW_basins_gdf=HW_basins_gdf,
                    HW_basins=HW_basins,
                    output_netcdf_filename=output_netcdf_filename,
                )
            )
            _report_external_artifact("map", map_file)

        except Exception as e:
            warn(f"Unexpected error while generating the map: {e}")
