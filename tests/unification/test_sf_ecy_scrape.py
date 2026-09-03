"""ecy_scrape is the one function taken from nhf in this concern."""
import inspect

from tests.unification.fabrics import baseline_function_ast, current_function_ast

NHF_SF = "src/assist/nhf/sf_data_retrieval_v2_1.py"
BASELINE = "c47ff07"


def test_ecy_scrape_is_verbatim_nhf():
    import assist.common.sf_data_retrieval as common

    assert current_function_ast(common.ecy_scrape) == baseline_function_ast(
        NHF_SF, "ecy_scrape", BASELINE
    )


def test_ecy_scrape_has_the_zip_handling_nhm_lacked():
    import assist.common.sf_data_retrieval as common

    source = inspect.getsource(common.ecy_scrape)
    assert "zipfile" in source
    assert "DSG_DV" in source or "tempfile" in source


def test_ecy_scrape_documents_its_return():
    import assist.common.sf_data_retrieval as common

    doc = inspect.getdoc(common.ecy_scrape) or ""
    assert "temp_df" in doc
