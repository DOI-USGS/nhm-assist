#!/usr/bin/env python3

# import matplotlib as mplib
import matplotlib.pyplot as plt
import numpy as np

# import matplotlib.dates as mdates


def efc(df, flow_col):
    """
    Classifies all daily flows in the streamflow observation file using all the steps for Environmental Flow Component (EFC) classification.

    Parameters
    ----------
    df : DataFrame
        A dataframe with streamflow values (additional columns are allowed).
    flow_col : argument
        The `flow_col` argument specifies the name of the column in the df, eg. "discharge"
    
    Returns
    -------
    Dataframe with EFC and ascending/descending flow values as attributes in the DataFrame.
    """
    
    df2 = df.copy()

    # Compute recurrence intervals
    df2["ri"] = compute_recurrence_interval(df2.loc[:, flow_col])

    # Compute high/low
    df2["high_low"] = compute_high_low(df2.loc[:, flow_col])

    # Compute EFC
    df2["efc"] = compute_efc(df2, flow_col=flow_col)

    return df2


def get_first_valid(ds):
    """
    Parameters
    ----------
    ds : Pandas timeseries
        Pandas timeseries of streamflow values

    Returns
    -------
    first_valid: int
        Index to the first valid non-zero streamflow value
    """
    
    # Get the index to the first valid (zero or greater) streamflow value
    # Expects a Pandas time series
    first_valid = None

    for dd in range(0, len(ds.index) - 1):
        if (ds[dd] >= 0.0) and (ds[dd + 1] >= 0.0):
            first_valid = dd
            break
    return first_valid


def compute_efc(df, flow_col):
    """
    Computes the Environmental Flow Component classifications for a streamflow timeseries. This routine expects a Pandas dataframe that has recurrence interval column named `ri` and a high_low classification column named `high_low`. Name of the streamflow column is specified with the `flow_col` argument.

    Parameters
    ----------
    df : DataFrame
        A dataframe with streamflow values (additional columns are allowed).
    flow_col : argument
        The `flow_col` argument specifies the name of the column in the df, eg. "discharge"
    
    Returns
    -------
    Dataframe with EFC and ascending/descending flow values as attributes in the DataFrame.
    """
    # ~~~~~~~~
    # Part 3 - Assign EFC classifications
    # ~~~~~~~~
    # EFC classifications
    # 1 = Large floods
    # 2 = Small floods
    # 3 = High flow pulses
    # 4 = Low flows
    # 5 = Extreme low flows

    numdays = len(df.index)

    # Initialize the efc array
    efc_arr = np.ones(numdays, dtype="int") * -1
    
    # pull out the flow arrays to evaluate
    high_low = df["high_low"].values
    ri = df["ri"].values
    ts_q = df.loc[:, flow_col]

    # 10th percentile of the streamflow obs
    p10_q = ts_q[ts_q > 0.0].quantile(q=0.1, interpolation="nearest").item()

    for dd in range(0, numdays):
        if ts_q.iloc[dd] >= 0.0:
            if high_low[dd] > 1:
                # High flows
                if ri[dd] > 10.0:
                    efc_arr[dd] = 1  # Large flood
                elif ri[dd] > 2.0:
                    efc_arr[dd] = 2  # Small flood
                else:
                    efc_arr[dd] = 3  # Default to high flow pulse
            elif high_low[dd] == 1:
                # Low flow events
                if ts_q.iloc[dd] < p10_q:
                    # Extreme low flow event
                    efc_arr[dd] = 5
                else:
                    efc_arr[dd] = 4  # Default to low flow
    return efc_arr


def compute_high_low(df):
    """
    Classify streamflow in high flows (1, 2, 3) and low flows (4, 5)

    Parameters
    ----------
    df : DataFrame
        A Pandas timeseries of streamflow values (additional columns are allowed).
        
    Returns
    -------
    high_low : ndarray
        high/low flow classification
    """

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # Part 2 - Classify the high and low flows
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # High/Low flow classifications
    # 1 = low flow
    # 2 = Ascending limb
    # 3 = Descending limb

    numdays = len(df.index)
    ts_q = df

    # Setup array for high/low flow classifications
    high_low = np.ones(numdays, dtype="int") * -1

    # Median and 75th percentile of the streamflow obs
    median_q = ts_q[ts_q > 0.0].quantile(q=0.5, interpolation="nearest").item()
    p75_q = ts_q[ts_q > 0.0].quantile(q=0.75, interpolation="nearest").item()

    has_gap = False

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # Now classify the remaining daily flows
    # for cday in range(first_valid+2, numdays):
    for cday in range(1, numdays):
        prior_day = cday - 1

        if ts_q.iloc[cday] >= 0.0:
            if has_gap:
                # Initialize the first two valid days to a low flow
                high_low[cday] = 1
                high_low[cday + 1] = 1

                # Compute the 25% greater and 25% lesser flows
                qq125 = ts_q.iloc[cday] * 1.25  # 25% greater
                qq75 = ts_q.iloc[cday] * 0.75  # 25% less

                # Check if the flow in day 1 greater than the median or if the flow on day 2 is
                # 25% greater than on day 1
                if (ts_q.iloc[cday] > median_q) or (ts_q.iloc[cday + 1] >= qq125):
                    # Classify as ascending
                    high_low[cday] = 2
                    high_low[cday + 1] = 2

                # If day 2 flow drops by more than 25% compared to day 1 then it is descending
                if ts_q.iloc[cday + 1] < qq75:
                    high_low[cday] = 3
                    high_low[cday + 1] = 3

                has_gap = False
                continue

            # Compute the 25% greater, 25% lesser and 10% lesser prior day flows
            qq125 = ts_q.iloc[prior_day] * 1.25  # 25% greater
            # qq75 = ts_q[prior_day] * .75   # 25% less
            qq90 = ts_q.iloc[prior_day] * 0.9  # 10% less

            if ts_q.iloc[cday] < median_q:
                # Classify as a low flow day
                high_low[cday] = 1
                continue

            if high_low[prior_day] == 1:
                # The prior day was a low flow day, check if today is still a
                # low flow or an ascending limb
                if ts_q.iloc[cday] > p75_q or (ts_q.iloc[cday] > median_q and ts_q.iloc[cday] > qq125):
                    # Ascending flow if Q > 75th percentile
                    high_low[cday] = 2
                else:
                    high_low[cday] = 1
            elif high_low[prior_day] == 2:
                # The prior day is an ascending limb (2) so continue ascending
                # until daily flow decreases by more than 10% at which time
                # descending (3) limb is initiated.
                if ts_q.iloc[cday] > qq90:
                    high_low[cday] = 2  # Ascending
                else:
                    high_low[cday] = 3  # Descending
            elif high_low[prior_day] == 3:
                # If the prior day is descending then ascending is restarted if
                # current day flow increases by more than 25%.
                if ts_q.iloc[cday] > qq125:
                    high_low[cday] = 2  # Ascending
                else:
                    high_low[cday] = 3  # Descending

                # If the rate of decrease drops below 10% per day
                # then event is ended unless the flow is still greater
                # than the 75th percentile.
                if ts_q.iloc[cday] > p75_q:
                    high_low[cday] = 3  # Descending
                else:
                    if ts_q.iloc[cday] < qq90:
                        high_low[cday] = 1  # Low flow
                    else:
                        high_low[cday] = 3  # Descending
        else:
            # We have a missing value
            has_gap = True

    return high_low


def compute_recurrence_interval(df):
    """
    Compute the recurrence intervals for streamflow.

    Parameters
    ----------
    df : DataFrame
        A Pandas timeseries of streamflow values (additional columns are allowed).
        
    Returns
    -------
    high_low : ndarray
        ndarray of recurrence intervals
    """
    df_arr = df.values

    ri = np.zeros(len(df.index))
    ri[:] = np.nan

    # Get array of indices that would result in a sorted array
    sorted_ind = np.argsort(df_arr)

    numobs = df_arr[df_arr > 0.0,].shape[0]  # Number of observations > 0.
    nyr = float(numobs) / 365.0  # Number of years of non-zero observations

    nz_cnt = 0  # non-zero value counter
    for si in sorted_ind:
        if df_arr[si] > 0.0:
            nz_cnt += 1
            rank = numobs - nz_cnt + 1
            ri[si] = (nyr + 1.0) / float(rank)
    return ri


# Helper functions for plotting, developed by P.A. Norton, USGS Dakota Water Science Center
def plot_efc(df, flow_col):
    """
    Makes a plot of the discharge timeseries and EFC class.
    
    Parameters
    ----------
    df : DataFrame
        A dataframe with streamflow values (additional columns are allowed).
    flow_col : argument
        The `flow_col` argument specifies the name of the column in the df, eg. "discharge"
    
    Returns
    -------
    plot object
    """
    fig, ax = plt.subplots(nrows=1, figsize=(15, 5), layout="tight")

    mkrsize = 9.1

    # cmap = ListedColormap(['#000000', '#cb4335', '#f8c471', '#95a5a6', '#76d7c4', '#154360'])
    cmap = ["#000000", "#cb4335", "#f8c471", "#95a5a6", "#76d7c4", "#154360"]
    labels = [
        "",
        "Large flood",
        "Small flood",
        "High flow pulse",
        "Low flow",
        "Extreme low flow",
    ]

    ax.plot(df.index, df[flow_col], c="grey", lw=0.5, alpha=0.5)

    for xx in range(1, 6):
        sdf = df[df["efc"] == xx]

        if sdf.shape[0] != 0:
            ax.scatter(
                sdf.index,
                sdf[flow_col],
                c=cmap[xx],
                s=mkrsize,
                lw=0,
                alpha=0.7,
                label=labels[xx],
            )

    ax.set_title("Environmental Flow Component (EFC) Classifications", fontsize=10)
    ax.legend(loc="upper left", framealpha=0.5)


def plot_high_low(df, flow_col):
    """
    Makes a plot of the discharge timeseries and High/Low classifications.
    
    Parameters
    ----------
    df : DataFrame
        A dataframe with streamflow values (additional columns are allowed).
    flow_col : argument
        The `flow_col` argument specifies the name of the column in the df, eg. "discharge"
    
    Returns
    -------
    plot object
    """
    fig, ax = plt.subplots(nrows=1, figsize=(15, 5), layout="tight")

    mkrsize = 9.1

    cmap = ["", "#00cc66", "#ff9933", "#9933ff"]
    labels = ["", "Low flow", "Ascending limb", "Descending limb"]

    ax.plot(df.index, df[flow_col], c="grey", lw=0.5, alpha=0.5)

    for xx in range(1, 4):
        sdf = df[df["high_low"] == xx]

        if sdf.shape[0] != 0:
            ax.scatter(
                sdf.index,
                sdf[flow_col],
                c=cmap[xx],
                s=mkrsize,
                lw=0,
                alpha=0.7,
                label=labels[xx],
            )

    ax.set_title("High/Low classifications", fontsize=10)
    ax.legend(loc="upper left", framealpha=0.5)
