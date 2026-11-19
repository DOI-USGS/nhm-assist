"""Checks for paths a user must fill in before running a workflow notebook.

Workflow templates ship with ``USER_PATH_PLACEHOLDER`` where a user has to put
their own path (a run-output folder, for example), so no contributor's absolute
path is committed. ``require_user_path`` stops the notebook with a message that
names the setting to edit, instead of failing later on a missing folder.
"""

from __future__ import annotations

import pathlib as pl

USER_PATH_PLACEHOLDER = "<USER_PATH_HERE>"


def is_placeholder(value) -> bool:
    """True when ``value`` is empty or still holds a ``<...>`` placeholder."""
    if value is None:
        return True
    text = str(value).strip()
    return not text or USER_PATH_PLACEHOLDER in text or (text.startswith("<") and text.endswith(">"))


def require_user_path(value, name: str, must_exist: bool = True, example: str = "") -> pl.Path:
    """Return ``value`` as a Path, or raise if the user has not set it.

    Raises ``ValueError`` when ``value`` is empty or still the placeholder, and
    ``FileNotFoundError`` when ``must_exist`` is true and the path does not exist.
    ``name`` is the setting the user edits; ``example`` is shown in the message.
    """
    hint = f" For example: {example}" if example else ""
    if is_placeholder(value):
        raise ValueError(
            f"`{name}` is not set. Edit it in the Parameters cell: replace "
            f"{USER_PATH_PLACEHOLDER} with your path, then re-run.{hint}"
        )
    path = pl.Path(str(value).strip())
    if must_exist and not path.exists():
        raise FileNotFoundError(
            f"`{name}` does not exist: {path}. Check the path in the Parameters cell.{hint}"
        )
    return path


def require_user_value(value, name: str, example: str = "") -> str:
    """Return ``value`` as a string, or raise ``ValueError`` if it is unset.

    For settings that are not paths, such as a login name.
    """
    if is_placeholder(value):
        hint = f" For example: {example}" if example else ""
        raise ValueError(f"`{name}` is not set. Edit it in the config cell, then re-run.{hint}")
    return str(value).strip()
