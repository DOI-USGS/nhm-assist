# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.3
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %%
import warnings
import pandas as pd
import numpy as np
import pathlib as pl
import xarray as xr
import sys
import os
import json
import html

from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

import folium
import branca.colormap as bcm

from rich.console import Console
from rich import pretty

warnings.filterwarnings("ignore")
pretty.install()
con = Console()

# %%
root_folder = "nhm-assist"
root_dir = pl.Path(os.getcwd().rsplit(root_folder, 1)[0] + root_folder)
sys.path.append(str(root_dir))

from nhm_helpers.nhm_assist_utilities import load_subdomain_config
from nhm_helpers.nhm_hydrofabric import (
    create_hru_gdf,
    create_segment_gdf,
    create_poi_df,
)

config = load_subdomain_config(root_dir)

hru_gdf, hru_txt, hru_cal_level_txt = create_hru_gdf(
    root_dir=root_dir,
    model_dir=config["model_dir"],
    GIS_format=config["GIS_format"],
    param_filename=config["param_filename"],
    nhru_params=config["nhru_params"],
    nhru_nmonths_params=config["nhru_nmonths_params"],
)

seg_gdf, seg_txt = create_segment_gdf(
    model_dir=config["model_dir"],
    GIS_format=config["GIS_format"],
    param_filename=config["param_filename"],
)

poi_df = create_poi_df(
    root_dir=root_dir,
    model_dir=config["model_dir"],
    param_filename=config["param_filename"],
    control_file_name=config["control_file_name"],
    hru_gdf=hru_gdf,
    gages_file=config["gages_file"],
    default_gages_file=config["default_gages_file"],
    nwis_gage_nobs_min=config["nwis_gage_nobs_min"],
    seg_gdf=seg_gdf,
)

poi_df = poi_df.copy()
poi_df["poi_id"] = poi_df["poi_id"].astype(str)

display(poi_df.head())

# %%
temp_config = {
    "poi_streamflow_nc": config["out_dir"] / "seg_outflow.nc",
    "poi_temperature_obs_nc": config["out_dir"] / "poi_water_temp.nc",
    "cbh_file": config["model_dir"] / "cbh.nc",
    "air_temp_rolling_days": 7,
    "predictor_cols": [
        "tair_mean",
        "tair_mean_lag1",
        "tair_mean_roll",
        "log_flow",
        "sin_doy",
        "cos_doy",
    ],
    "min_training_rows": 10,
    "min_train_rows": 5,
    "min_test_rows": 3,
    "map_center": [44.0, -122.7],
    "map_zoom": 7,
    "predictions_csv": config["out_dir"] / "all_poi_predicted_stream_temp.csv",
    "metrics_csv": config["out_dir"] / "all_poi_stream_temp_metrics.csv",
    "coefficients_csv": config["out_dir"] / "all_poi_stream_temp_coefficients.csv",
    "predictions_nc": config["out_dir"] / "all_poi_predicted_stream_temp.nc",
    "folium_kge_html": config["out_dir"] / "stream_temperature_kge_map.html",
    "folium_temp_html": config["out_dir"] / "stream_temperature_mean_map.html",
}


# %%
def kling_gupta_efficiency(obs, sim):
    obs = np.asarray(obs, dtype=float)
    sim = np.asarray(sim, dtype=float)

    mask = np.isfinite(obs) & np.isfinite(sim)
    obs = obs[mask]
    sim = sim[mask]

    if len(obs) < 2:
        return np.nan

    obs_mean = np.mean(obs)
    sim_mean = np.mean(sim)
    obs_std = np.std(obs, ddof=1)
    sim_std = np.std(sim, ddof=1)

    if obs_mean == 0 or obs_std == 0:
        return np.nan

    r = np.corrcoef(obs, sim)[0, 1]
    alpha = sim_std / obs_std
    beta = sim_mean / obs_mean

    return 1 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)


def load_air_temp_series_from_cbh(cbh_file):
    with xr.open_dataset(cbh_file) as ds:
        if "nhru" in ds.dims and "nhm_id" not in ds.dims:
            tmin = ds["tmin"].mean(dim="nhru")
            tmax = ds["tmax"].mean(dim="nhru")
        elif "nhm_id" in ds.dims:
            tmin = ds["tmin"].mean(dim="nhm_id")
            tmax = ds["tmax"].mean(dim="nhm_id")
        else:
            raise ValueError(f"Could not identify HRU dimension in {cbh_file}")

        tair = (tmin + tmax) / 2.0
        df = tair.to_series().reset_index()
        df.columns = ["date", "tair_mean"]
        df["date"] = pd.to_datetime(df["date"]).dt.floor("D")

    return df


def load_poi_streamflow_series(seg_outflow_file, poidf):
    da = xr.load_dataarray(seg_outflow_file)

    seg_dim_candidates = [d for d in da.dims if d.lower() in ["npoigages", "poi_id", "nhm_seg", "nsegment", "segment"]]
    if len(seg_dim_candidates) == 0:
        raise ValueError(f"Could not identify segment dimension in {da.dims}")

    seg_dim = seg_dim_candidates[0]

    if "poi_id" in da.coords:
        poi_ids = pd.Index(da["poi_id"].values.astype(str), name="poi_id")
        out = da
        if seg_dim != "poi_id":
            out = out.rename({seg_dim: "poi_id"})
        out = out.assign_coords(poi_id=poi_ids.values)
    else:
        raise ValueError(
            f"{seg_outflow_file} needs a poi_id coordinate. "
            "Use the POI-filtered seg_outflow output from Notebook 4."
        )

    flow_df = out.to_pandas()
    if isinstance(flow_df, pd.Series):
        flow_df = flow_df.to_frame()

    flow_df.index = pd.to_datetime(flow_df.index).floor("D")
    flow_df.index.name = "date"
    flow_df.columns = flow_df.columns.astype(str)

    flow_df = flow_df.reset_index().melt(
        id_vars="date",
        var_name="poi_id",
        value_name="seg_outflow",
    )
    flow_df["poi_id"] = flow_df["poi_id"].astype(str)

    return flow_df


def load_observed_temperature_series(temp_nc_file):
    ds = xr.open_dataset(temp_nc_file)

    var_candidates = list(ds.data_vars)
    if "water_temperature" in var_candidates:
        varname = "water_temperature"
    elif "poi_water_temperature" in var_candidates:
        varname = "poi_water_temperature"
    elif "obs_stream_temp" in var_candidates:
        varname = "obs_stream_temp"
    else:
        raise ValueError(
            f"Could not identify observed temperature variable in {temp_nc_file}. "
            f"Available variables: {var_candidates}"
        )

    da = ds[varname]

    poi_dim_candidates = [d for d in da.dims if d.lower() in ["poi_id", "npoigages", "poiid"]]
    if len(poi_dim_candidates) == 0:
        raise ValueError(f"Could not identify poi dimension in {da.dims}")

    poi_dim = poi_dim_candidates[0]
    if poi_dim != "poi_id":
        da = da.rename({poi_dim: "poi_id"})

    obs_df = da.to_pandas()
    if isinstance(obs_df, pd.Series):
        obs_df = obs_df.to_frame()

    obs_df.index = pd.to_datetime(obs_df.index).floor("D")
    obs_df.index.name = "date"
    obs_df.columns = obs_df.columns.astype(str)

    obs_df = obs_df.reset_index().melt(
        id_vars="date",
        var_name="poi_id",
        value_name="obs_stream_temp",
    )
    obs_df["poi_id"] = obs_df["poi_id"].astype(str)

    return obs_df


def add_time_features(df, rolling_days=7):
    df = df.sort_values("date").copy()
    doy = df["date"].dt.dayofyear

    df["sin_doy"] = np.sin(2 * np.pi * doy / 365.25)
    df["cos_doy"] = np.cos(2 * np.pi * doy / 365.25)
    df["log_flow"] = np.log1p(df["seg_outflow"].clip(lower=0.0))
    df["tair_mean_lag1"] = df["tair_mean"].shift(1)
    df["tair_mean_roll"] = df["tair_mean"].rolling(rolling_days, min_periods=1).mean()

    return df


def fit_temperature_model_for_poi(
    poi_id,
    flow_df,
    air_df,
    obs_df,
    predictor_cols,
    rolling_days,
    min_training_rows,
    min_train_rows,
    min_test_rows,
):
    poi_flow = flow_df.loc[flow_df["poi_id"] == str(poi_id), ["date", "seg_outflow"]].copy()
    poi_obs = obs_df.loc[obs_df["poi_id"] == str(poi_id), ["date", "obs_stream_temp"]].copy()

    reg_df = (
        poi_flow.merge(air_df, on="date", how="inner")
        .merge(poi_obs, on="date", how="inner")
        .sort_values("date")
        .reset_index(drop=True)
    )

    reg_df = add_time_features(reg_df, rolling_days=rolling_days)
    reg_df = reg_df.dropna(subset=predictor_cols + ["obs_stream_temp"]).reset_index(drop=True)

    if len(reg_df) < min_training_rows:
        return None, None, None

    X = reg_df[predictor_cols].copy()
    y = reg_df["obs_stream_temp"].copy()

    split_date = pd.to_datetime(reg_df["date"]).quantile(0.7)
    train_mask = pd.to_datetime(reg_df["date"]) <= split_date
    test_mask = ~train_mask

    if train_mask.sum() < min_train_rows or test_mask.sum() < min_test_rows:
        return None, None, None

    X_train = X.loc[train_mask]
    y_train = y.loc[train_mask]
    X_test = X.loc[test_mask]
    y_test = y.loc[test_mask]

    model = LinearRegression()
    model.fit(X_train, y_train)

    reg_df["pred_stream_temp"] = model.predict(X)
    reg_df["dataset"] = np.where(train_mask, "train", "test")
    reg_df["poi_id"] = str(poi_id)

    train_pred = model.predict(X_train)
    test_pred = model.predict(X_test)

    metrics_df = pd.DataFrame(
        {
            "poi_id": [str(poi_id), str(poi_id)],
            "dataset": ["train", "test"],
            "n_obs": [len(y_train), len(y_test)],
            "rmse": [
                np.sqrt(mean_squared_error(y_train, train_pred)),
                np.sqrt(mean_squared_error(y_test, test_pred)),
            ],
            "mae": [
                mean_absolute_error(y_train, train_pred),
                mean_absolute_error(y_test, test_pred),
            ],
            "r2": [
                r2_score(y_train, train_pred),
                r2_score(y_test, test_pred),
            ],
            "kge": [
                kling_gupta_efficiency(y_train, train_pred),
                kling_gupta_efficiency(y_test, test_pred),
            ],
            "split_date": [split_date, split_date],
        }
    )

    coef_df = pd.DataFrame(
        {
            "poi_id": str(poi_id),
            "predictor": predictor_cols + ["intercept"],
            "coefficient": list(model.coef_) + [model.intercept_],
        }
    )

    return reg_df, metrics_df, coef_df


def safe_float(val, ndigits=2):
    if pd.isna(val):
        return "nan"
    return f"{float(val):.{ndigits}f}"


# %%
air_df = load_air_temp_series_from_cbh(temp_config["cbh_file"])
flow_df = load_poi_streamflow_series(temp_config["poi_streamflow_nc"], poi_df)
obs_df = load_observed_temperature_series(temp_config["poi_temperature_obs_nc"])

air_df["date"] = pd.to_datetime(air_df["date"]).dt.tz_localize(None)
flow_df["date"] = pd.to_datetime(flow_df["date"]).dt.tz_localize(None)
obs_df["date"] = pd.to_datetime(obs_df["date"]).dt.tz_localize(None)

con.print(f"Air temperature rows: {len(air_df)}")
con.print(f"Modeled flow rows: {len(flow_df)}")
con.print(f"Observed temperature rows: {len(obs_df)}")

# %%
all_pred_list = []
all_metrics_list = []
all_coef_list = []
failed_pois = []

poi_ids = sorted(poi_df["poi_id"].astype(str).unique().tolist())

for poi_id in poi_ids:
    try:
        pred_df, metrics_df, coef_df = fit_temperature_model_for_poi(
            poi_id=poi_id,
            flow_df=flow_df,
            air_df=air_df,
            obs_df=obs_df,
            predictor_cols=temp_config["predictor_cols"],
            rolling_days=temp_config["air_temp_rolling_days"],
            min_training_rows=temp_config["min_training_rows"],
            min_train_rows=temp_config["min_train_rows"],
            min_test_rows=temp_config["min_test_rows"],
        )

        if pred_df is None:
            failed_pois.append((poi_id, "insufficient overlapping data"))
            continue

        all_pred_list.append(pred_df)
        all_metrics_list.append(metrics_df)
        all_coef_list.append(coef_df)

    except Exception as e:
        failed_pois.append((poi_id, str(e)))

con.print(f"POIs successfully modeled: {len(all_pred_list)}")
con.print(f"POIs failed/skipped: {len(failed_pois)}")

pd.DataFrame(failed_pois, columns=["poi_id", "reason"]).head(20)

# %%
if len(all_pred_list) == 0:
    raise RuntimeError("No POIs produced regression results.")

all_pred_df = pd.concat(all_pred_list, ignore_index=True)
all_metrics_df = pd.concat(all_metrics_list, ignore_index=True)
all_coef_df = pd.concat(all_coef_list, ignore_index=True)

all_pred_df = all_pred_df.sort_values(["poi_id", "date"]).reset_index(drop=True)
all_metrics_df = all_metrics_df.sort_values(["poi_id", "dataset"]).reset_index(drop=True)
all_coef_df = all_coef_df.sort_values(["poi_id", "predictor"]).reset_index(drop=True)

all_pred_df.to_csv(temp_config["predictions_csv"], index=False)
all_metrics_df.to_csv(temp_config["metrics_csv"], index=False)
all_coef_df.to_csv(temp_config["coefficients_csv"], index=False)

con.print(f"Wrote {temp_config['predictions_csv']}")
con.print(f"Wrote {temp_config['metrics_csv']}")
con.print(f"Wrote {temp_config['coefficients_csv']}")

display(all_metrics_df.head(20))

# %%
pred_wide = (
    all_pred_df[["date", "poi_id", "pred_stream_temp"]]
    .pivot(index="date", columns="poi_id", values="pred_stream_temp")
    .sort_index()
)

obs_wide = (
    all_pred_df[["date", "poi_id", "obs_stream_temp"]]
    .pivot(index="date", columns="poi_id", values="obs_stream_temp")
    .sort_index()
)

common_pois = sorted(set(pred_wide.columns).intersection(obs_wide.columns))
pred_wide = pred_wide[common_pois]
obs_wide = obs_wide.reindex(pred_wide.index)[common_pois]

temp_ds = xr.Dataset(
    data_vars={
        "pred_stream_temp": (("time", "poi_id"), pred_wide.to_numpy()),
        "obs_stream_temp": (("time", "poi_id"), obs_wide.to_numpy()),
    },
    coords={
        "time": pd.to_datetime(pred_wide.index),
        "poi_id": common_pois,
    },
    attrs={
        "title": "Predicted and observed POI stream temperatures",
        "source": "Regression post-processing of Notebook 4 pywatershed outputs and POI temperature NetCDF",
    },
)

temp_ds["pred_stream_temp"].attrs = {
    "long_name": "Predicted stream temperature",
    "units": "degC",
}
temp_ds["obs_stream_temp"].attrs = {
    "long_name": "Observed stream temperature",
    "units": "degC",
}

temp_ds.to_netcdf(temp_config["predictions_nc"])
con.print(f"Wrote {temp_config['predictions_nc']}")
temp_ds

# %%
test_metrics_df = (
    all_metrics_df.loc[all_metrics_df["dataset"] == "test"]
    .copy()
)

temp_summary_df = (
    all_pred_df.loc[all_pred_df["dataset"] == "test"]
    .groupby("poi_id", as_index=False)
    .agg(
        mean_obs_temp=("obs_stream_temp", "mean"),
        mean_pred_temp=("pred_stream_temp", "mean"),
        max_obs_temp=("obs_stream_temp", "max"),
        max_pred_temp=("pred_stream_temp", "max"),
        n_test_days=("obs_stream_temp", "size"),
    )
)

map_df = (
    poidf[[
        "poi_id",
        "poi_name",
        "latitude",
        "longitude",
        "drainage_area",
        "nhm_calib",
    ]]
    .copy()
    .merge(test_metrics_df, on="poi_id", how="left")
    .merge(temp_summary_df, on="poi_id", how="left")
)

display(map_df.head())


# %%
def popup_html_for_poi(row):
    title = html.escape(str(row.get("poi_name", row["poi_id"])))
    return f"""
    <div style="width: 320px;">
        <h4 style="margin-bottom: 8px;">{title}</h4>
        <b>POI ID:</b> {html.escape(str(row.get("poi_id", "")))}<br>
        <b>Latitude:</b> {safe_float(row.get("latitude"), 4)}<br>
        <b>Longitude:</b> {safe_float(row.get("longitude"), 4)}<br>
        <b>Drainage area:</b> {safe_float(row.get("drainage_area"), 2)}<br>
        <b>NHM calib:</b> {html.escape(str(row.get("nhm_calib", "")))}<br>
        <hr style="margin: 8px 0;">
        <b>Test KGE:</b> {safe_float(row.get("kge"), 3)}<br>
        <b>Test RMSE:</b> {safe_float(row.get("rmse"), 3)} degC<br>
        <b>Test MAE:</b> {safe_float(row.get("mae"), 3)} degC<br>
        <b>Test R²:</b> {safe_float(row.get("r2"), 3)}<br>
        <b>Test days:</b> {safe_float(row.get("n_test_days"), 0)}<br>
        <hr style="margin: 8px 0;">
        <b>Mean observed temp:</b> {safe_float(row.get("mean_obs_temp"), 2)} degC<br>
        <b>Mean predicted temp:</b> {safe_float(row.get("mean_pred_temp"), 2)} degC<br>
        <b>Max observed temp:</b> {safe_float(row.get("max_obs_temp"), 2)} degC<br>
        <b>Max predicted temp:</b> {safe_float(row.get("max_pred_temp"), 2)} degC<br>
    </div>
    """


def build_kge_map(map_df, map_center, map_zoom):
    valid = map_df.dropna(subset=["latitude", "longitude", "kge"]).copy()

    m = folium.Map(location=map_center, zoom_start=map_zoom, tiles="CartoDB Positron")

    kge_colormap = bcm.LinearColormap(
        colors=["#b2182b", "#fddbc7", "#d1e5f0", "#2166ac"],
        vmin=-1.0,
        vmax=1.0,
        caption="Test Kling-Gupta Efficiency",
    )

    good_fg = folium.FeatureGroup(name="KGE markers", show=True)
    missing_fg = folium.FeatureGroup(name="No test metrics", show=True)

    for _, row in valid.iterrows():
        color = kge_colormap(row["kge"])
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=7,
            color="#333333",
            weight=1,
            fill=True,
            fill_color=color,
            fill_opacity=0.9,
            popup=folium.Popup(popup_html_for_poi(row), max_width=350),
            tooltip=f"{row['poi_id']} | KGE={safe_float(row['kge'], 3)}",
        ).add_to(good_fg)

    for _, row in map_df.loc[map_df["kge"].isna()].dropna(subset=["latitude", "longitude"]).iterrows():
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=5,
            color="#777777",
            weight=1,
            fill=True,
            fill_color="#cccccc",
            fill_opacity=0.7,
            popup=folium.Popup(popup_html_for_poi(row), max_width=350),
            tooltip=f"{row['poi_id']} | no test metrics",
        ).add_to(missing_fg)

    good_fg.add_to(m)
    missing_fg.add_to(m)
    kge_colormap.add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)

    return m


def build_mean_temp_map(map_df, map_center, map_zoom):
    valid = map_df.dropna(subset=["latitude", "longitude", "mean_pred_temp"]).copy()

    m = folium.Map(location=map_center, zoom_start=map_zoom, tiles="CartoDB Positron")

    temp_min = float(valid["mean_pred_temp"].min()) if len(valid) else 0.0
    temp_max = float(valid["mean_pred_temp"].max()) if len(valid) else 1.0

    temp_colormap = bcm.LinearColormap(
        colors=["#313695", "#74add1", "#fdae61", "#a50026"],
        vmin=temp_min,
        vmax=temp_max,
        caption="Mean predicted test-period stream temperature (degC)",
    )

    pred_fg = folium.FeatureGroup(name="Predicted mean temp", show=True)
    obs_fg = folium.FeatureGroup(name="Observed mean temp labels", show=False)

    for _, row in valid.iterrows():
        pred_color = temp_colormap(row["mean_pred_temp"])

        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=7,
            color="#333333",
            weight=1,
            fill=True,
            fill_color=pred_color,
            fill_opacity=0.9,
            popup=folium.Popup(popup_html_for_poi(row), max_width=350),
            tooltip=f"{row['poi_id']} | pred mean={safe_float(row['mean_pred_temp'], 2)} degC",
        ).add_to(pred_fg)

        if pd.notna(row["mean_obs_temp"]):
            folium.Marker(
                location=[row["latitude"], row["longitude"]],
                icon=folium.DivIcon(
                    html=f"""
                    <div style="
                        font-size: 10px;
                        color: #111111;
                        background-color: rgba(255,255,255,0.8);
                        border: 1px solid #888;
                        border-radius: 3px;
                        padding: 1px 3px;
                        white-space: nowrap;
                    ">
                        obs {safe_float(row['mean_obs_temp'], 1)}°C
                    </div>
                    """
                ),
                tooltip=f"{row['poi_id']} | obs mean={safe_float(row['mean_obs_temp'], 2)} degC",
            ).add_to(obs_fg)

    pred_fg.add_to(m)
    obs_fg.add_to(m)
    temp_colormap.add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)

    return m


# %%
kge_map = build_kge_map(
    map_df=map_df,
    map_center=temp_config["map_center"],
    map_zoom=temp_config["map_zoom"],
)
kge_map.save(str(temp_config["folium_kge_html"]))
con.print(f"Wrote {temp_config['folium_kge_html']}")

temp_map = build_mean_temp_map(
    map_df=map_df,
    map_center=temp_config["map_center"],
    map_zoom=temp_config["map_zoom"],
)
temp_map.save(str(temp_config["folium_temp_html"]))
con.print(f"Wrote {temp_config['folium_temp_html']}")

kge_map

# %%
temp_map
