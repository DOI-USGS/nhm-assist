from pathlib import Path

from ipywidgets import widgets
from IPython.display import HTML, IFrame, clear_output, display
from assist.nhm.map_template import make_var_map
from assist.nhm.nhm_hydrofabric import make_hf_map_elements
from assist.nhm.nhm_output_visualization import retrieve_hru_output_info
from ipywidgets import VBox
from assist.nhm.output_plots import plot_colors
from assist.nhm.output_plots import (
    var_colors_dict,
    leg_only_dict,
    make_plot_var_for_hrus_in_poi_basin,
    oopla,
)
from assist.nhm.output_plots import create_streamflow_plot
from assist.nhm.map_template import make_streamflow_map
from assist.nhm.nhm_output_visualization import retrieve_hru_output_info

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

# import pathlib as pl
# import os
# root_dir = pl.Path(os.getcwd().rsplit("nhm-assist", 1)[0] + "nhm-assist")

def warn(msg: str):
    """Display a bold red warning in the notebook."""
    display(HTML(f"<div style='color:#b00020; font-weight:600'>{msg}</div>"))


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
    ids = poi_df.poi_id.values
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
        "HW_basins",
        "subdomain",
        "v",
    ):
        return
    _ensure_output_dirs()
    poi_id = _get_valid_poi()
    if poi_id is None:
        return
    fmap = make_var_map(
        root_dir=root_dir,
        out_dir=out_dir,
        output_var_sel=v.value,
        plot_start_date=plot_start_date,
        plot_end_date=plot_end_date,
        water_years=water_years,
        hru_gdf=hru_gdf,
        poi_df=poi_df,
        poi_id_sel=poi_id,
        seg_gdf=seg_gdf,
        html_maps_dir=html_maps_dir,
        year_list=year_list,
        sel_year=yr.value,
        Folium_maps_dir=Folium_maps_dir,
        HW_basins=HW_basins,
        subdomain=subdomain,
    )
    display(fmap)


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
    poi_id = _get_valid_poi()
    if poi_id is None:
        return
    make_plot_var_for_hrus_in_poi_basin(
        out_dir=out_dir,
        param_filename=param_filename,
        water_years=water_years,
        hru_gdf=hru_gdf,
        poi_df=poi_df,
        output_var_sel=v.value,
        poi_id_sel=poi_id,
        plot_start_date=plot_start_date,
        plot_end_date=plot_end_date,
        plot_colors=plot_colors,
        subdomain=subdomain,
        html_plots_dir=html_plots_dir,
    )


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
    poi_id = _get_valid_poi()
    if poi_id is None:
        return
    oopla(
        out_dir=out_dir,
        param_filename=param_filename,
        water_years=water_years,
        hru_gdf=hru_gdf,
        poi_df=poi_df,
        output_var_list=output_var_list,
        output_var_sel=v.value,
        poi_id_sel=poi_id,
        plot_start_date=plot_start_date,
        plot_end_date=plot_end_date,
        plot_colors=plot_colors,
        var_colors_dict=var_colors_dict,
        leg_only_dict=leg_only_dict,
        subdomain=subdomain,
        html_plots_dir=html_plots_dir,
    )


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
    clear_output(wait=True)
    display(
        VBox([v, yr, v2, plot_checks, btn_generate, out_map, out_summary, out_flux])
    )

    # Map
    if cb_map.value:
        with out_map:
            clear_output(wait=True)
            generate_map()

    # Summary TS
    if cb_summary.value:
        with out_summary:
            clear_output(wait=True)
            generate_summary()

    # Flux TS
    if cb_flux.value:
        with out_flux:
            clear_output(wait=True)
            generate_flux()


def _get_valid_poi1() -> str:
    """
    Return a valid POI identifier: the text‐input value if valid,
    otherwise the first available POI from poi_df.
    """
    if not _require_state("poi_df", "gage_txt"):
        return None
    ids = set(poi_df.poi_id.values)
    raw = gage_txt.value.strip() or next(iter(ids))
    return raw if raw in ids else next(iter(ids))

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
        "HW_basins_gdf",
        "HW_basins",
        "output_netcdf_filename",
        "gage_txt",
    ):
        return
    _ensure_output_dirs()
    with map_out:
        clear_output()
        poi_id_sel = _get_valid_poi1()
        if poi_id_sel is None:
            return

        try:
            map_file = make_streamflow_map(
                root_dir=root_dir,
                out_dir=out_dir,
                plot_start_date=plot_start_date,
                plot_end_date=plot_end_date,
                water_years=water_years,
                hru_gdf=hru_gdf,
                poi_df=poi_df,
                poi_id_sel=poi_id_sel,
                seg_gdf=seg_gdf,
                html_maps_dir=html_maps_dir,
                subdomain=subdomain,
                HW_basins_gdf=HW_basins_gdf,
                HW_basins=HW_basins,
                output_netcdf_filename=output_netcdf_filename,
            )

            # Display the result
            if isinstance(map_file, str):
                display(IFrame(src=map_file, width="100%", height="500px"))
            else:
                display(map_file)

        except (KeyError, IndexError):
            warn(
                f"The POI or streamgage ID “{poi_id_sel}” is not in the dataset. "
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
    with plot_out:
        clear_output()
        poi_id_sel = _get_valid_poi1()
        if poi_id_sel is None:
            return

        try:
            fplot = create_streamflow_plot(
                poi_id_sel=poi_id_sel,
                plot_start_date=plot_start_date,
                plot_end_date=plot_end_date,
                water_years=water_years,
                html_plots_dir=html_plots_dir,
                output_netcdf_filename=output_netcdf_filename,
                out_dir=out_dir,
                subdomain=subdomain,
            )
            if isinstance(fplot, str):
                display(IFrame(src=fplot, width="100%", height="500px"))
            else:
                display(fplot)

        except (KeyError, IndexError):
            warn(
                f"The streamgage ID “{poi_id_sel}” is not in the dataset. "
                "Please check the ID and try again."
            )
        except Exception as e:
            warn(f"Unexpected error while generating the plot: {e}")
