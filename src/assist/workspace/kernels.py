"""Registration of per-environment Jupyter kernels for nhm-assist.

A notebook's ``metadata.kernelspec`` only preselects a kernel in JupyterLab or
VS Code if a kernelspec with that exact name is actually registered on the
machine. Stamping the metadata and registering the spec therefore have to
happen together; this module owns the registration half.
"""

from __future__ import annotations

import json
import subprocess
import sys


DEFAULT_KERNEL_NAME = "nhm-assist"
DEFAULT_KERNEL_DISPLAY_NAME = "Python (nhm-assist)"
DEV_KERNEL_NAME = "nhm-assist-dev"
DEV_KERNEL_DISPLAY_NAME = "Python (nhm-assist dev)"

PAIRING_MODE_KERNELS: dict[str, tuple[str, str]] = {
    "local": (DEFAULT_KERNEL_NAME, DEFAULT_KERNEL_DISPLAY_NAME),
    "dev": (DEV_KERNEL_NAME, DEV_KERNEL_DISPLAY_NAME),
}


def list_kernel_names(*, runner=subprocess.run) -> set[str]:
    """Names of every kernelspec Jupyter can currently see.

    Returns an empty set rather than raising if Jupyter is unavailable or
    prints something unparseable — a missing kernel list should degrade into
    "register it again", never into a crashed notebook build.
    """
    result = runner(
        [sys.executable, "-m", "jupyter", "kernelspec", "list", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return set()
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return set()
    kernelspecs = payload.get("kernelspecs")
    if not isinstance(kernelspecs, dict):
        return set()
    return set(kernelspecs)


def ensure_kernel_registered(
    name: str,
    display_name: str,
    *,
    runner=subprocess.run,
) -> bool:
    """Register an ipykernel spec for the running interpreter if it is missing.

    Returns True if a new spec was installed, False if one already existed.
    """
    if name in list_kernel_names(runner=runner):
        return False

    runner(
        [
            sys.executable,
            "-m",
            "ipykernel",
            "install",
            "--user",
            "--name",
            name,
            "--display-name",
            display_name,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return True
