# Import Notebook Packages
import warnings
from collections.abc import KeysView
import networkx as nx
from pyPRMS import ParameterFile
from pyPRMS.metadata.metadata import MetaData
from rich import pretty

pretty.install()
warnings.filterwarnings("ignore")

### Helper Functions


def subset_stream_network(dag_ds, uscutoff_seg, dsmost_seg):  # (modified from Bandit)
    """
    Extract subset of stream network

    Parameters
    ----------
    dag_ds : Directed, acyclic graph of downstream stream network
    uscutoff_seg : List of upstream cutoff segments
    dsmost_seg : List of outlet segments to start extraction from

    Returns
    -------
    Stream network of extracted segments
    """

    # taken from Bandit bandit_helpers.py

    # Create the upstream graph
    dag_us = dag_ds.reverse()

    # Trim the u/s graph to remove segments above the u/s cutoff segments
    try:
        for xx in uscutoff_seg:
            try:
                dag_us.remove_nodes_from(nx.dfs_predecessors(dag_us, xx))

                # Also remove the cutoff segment itself
                dag_us.remove_node(xx)
            except KeyError:
                print(f"WARNING: nhm_segment {xx} does not exist in stream network")
    except TypeError:
        print(
            "\nSelected cutoffs should at least be an empty list instead of NoneType."
        )

    # =======================================
    # Given a d/s segment (dsmost_seg) create a subset of u/s segments

    # Get all unique segments u/s of the starting segment
    uniq_seg_us = set()
    if dsmost_seg:
        for xx in dsmost_seg:
            try:
                pred = nx.dfs_predecessors(dag_us, xx)
                uniq_seg_us = uniq_seg_us.union(
                    set(pred.keys()).union(set(pred.values()))
                )
            except KeyError:
                print(f"KeyError: Segment {xx} does not exist in stream network")

        # Get a subgraph in the dag_ds graph and return the edges
        dag_ds_subset = dag_ds.subgraph(uniq_seg_us).copy()

        node_outlets = [ee[0] for ee in dag_ds_subset.edges()]
        true_outlets = set(dsmost_seg).difference(set(node_outlets))

        # Add the downstream segments that exit the subgraph
        for xx in true_outlets:
            nhm_outlet = list(dag_ds.neighbors(xx))[0]
            dag_ds_subset.add_node(
                nhm_outlet, style="filled", fontcolor="white", fillcolor="grey"
            )
            dag_ds_subset.add_edge(xx, nhm_outlet)
            dag_ds_subset.nodes[xx]["style"] = "filled"
            dag_ds_subset.nodes[xx]["fontcolor"] = "white"
            dag_ds_subset.nodes[xx]["fillcolor"] = "blue"
    else:
        # No outlets specified so pull the full model
        dag_ds_subset = dag_ds

    return dag_ds_subset


def hrus_by_poi(pdb, poi):  # (custom code)
    """
    Extract subset of HRUs connected to the stream network upstream of slected poi.

    Parameters
    ----------
    pdb : DataFrame
        Database created using pyPRMS from parametr file
    poi : string
        Gage id 
    

    Returns
    -------
    List of HRUs for a poi or for pois in a list (gage)
    """
    if isinstance(poi, str):
        poi = [poi]
    elif isinstance(poi, KeysView):
        poi = list(poi)

    poi_hrus = {}
    nhm_seg = pdb.get("nhm_seg").data
    pois_dict = pdb.poi_to_seg
    seg_to_hru = pdb.seg_to_hru

    # Generate stream network for the model
    dag_streamnet = pdb.stream_network()

    for cpoi in poi:
        # Lookup global segment id for the current POI
        dsmost_seg = [nhm_seg[pois_dict[cpoi] - 1]]

        # Get subset of stream network for given POI
        dag_ds_subset = subset_stream_network(dag_streamnet, set(), dsmost_seg)

        # Create list of segments in the subset
        toseg_idx = list(set(xx[0] for xx in dag_ds_subset.edges))

        # Build list of HRUs that contribute to the POI
        final_hru_list = []

        for xx in toseg_idx:
            try:
                for yy in seg_to_hru[xx]:
                    final_hru_list.append(yy)
            except KeyError:
                # Not all segments have HRUs connected to them
                # print(f'{cpoi}: Segment {xx} has no HRUs connected to it')
                pass
        final_hru_list.sort()
        poi_hrus[cpoi] = final_hru_list

    return poi_hrus


def create_poi_group(hru_gdf, poi_df, param_filename):
    """
    Extract subset of HRUs connected to the stream network upstream of slected poi.

    Parameters
    ----------
    hru_gdf : geopandas GeoDataFrame()
        HRU geopandas.GeoDataFrame() from GIS data in subdomain.
    poi_df : pandas DataFrame()
        Pandas DataFrame() containing gages from the parameter file.
    param_filename : pathlib Path class 
        Path to parameter file. 
    
    Returns
    -------
    hru_gdf : geopandas GeoDataFrame()
        Revised HRU geopandas.GeoDataFrame() from GIS data in subdomain that includes a HW_id for each HRU.
    hru_poi_dict : {}
        Dictionary of pois and the list of HRUs in the contributing area for each poi.
    """
    
    """First, group HRUs to the downstream gagepoi that they contribute flow.
    """
    poi_list = poi_df["poi_id"].values.tolist()

    """Make a dictionary of pois and the list of HRUs in the contributing area for each poi.
    """
    prms_meta = MetaData().metadata  # loads metadata functions for pyPRMS
    pdb = ParameterFile(
        param_filename, metadata=prms_meta, verbose=False
    )  # loads parmaeterfile functions for pyPRMS

    hru_poi_dict = hrus_by_poi(pdb, poi_list)  # Helper function from pyPRMS

    """Sort the dictionary: this is important for the reverse dictionary (next step) to accurately give a poi_group
    to hrus that contribute to a downstream-gage.
    """
    sorted_items = sorted(
        hru_poi_dict.items(), key=lambda item: -len(item[1])
    )  # the - reverses the sorting order
    hru_poi_dict = dict(sorted_items[:])

    reversed_hru_poi_dict = {
        val: key for key in hru_poi_dict for val in hru_poi_dict[key]
    }

    # assigns poi_group value to all hrus #Keep for later application
    hru_gdf["poi_group"] = hru_gdf["nhm_id"].map(reversed_hru_poi_dict)

    return hru_gdf, hru_poi_dict
