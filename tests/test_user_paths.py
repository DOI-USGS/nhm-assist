import pytest

from assist.common.user_paths import (
    USER_PATH_PLACEHOLDER,
    is_placeholder,
    require_user_path,
    require_user_value,
)


@pytest.mark.parametrize("value", [None, "", "   ", USER_PATH_PLACEHOLDER, "<HPC_USER_HERE>"])
def test_unset_values_are_placeholders(value):
    assert is_placeholder(value)


def test_real_value_is_not_placeholder(tmp_path):
    assert not is_placeholder(tmp_path)
    assert not is_placeholder("jdoe")


def test_placeholder_path_raises_with_setting_name_and_example():
    with pytest.raises(ValueError, match=r"`run_dir` is not set.*For example: D:\\foo"):
        require_user_path(USER_PATH_PLACEHOLDER, "run_dir", example=r"D:\foo")


def test_missing_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="`run_dir` does not exist"):
        require_user_path(tmp_path / "nope", "run_dir")


def test_missing_path_allowed_when_not_required(tmp_path):
    assert require_user_path(tmp_path / "nope", "out", must_exist=False) == tmp_path / "nope"


def test_existing_path_returned(tmp_path):
    assert require_user_path(str(tmp_path), "run_dir") == tmp_path


def test_require_user_value():
    assert require_user_value(" jdoe ", "HPC_USER") == "jdoe"
    with pytest.raises(ValueError, match="`HPC_USER` is not set"):
        require_user_value("<HPC_USER_HERE>", "HPC_USER")
