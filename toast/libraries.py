# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Where ``import toast_lib.<name>`` finds its source, outside Blender.

``toast_lib.shapes`` is ``shapes.py`` and ``toast_lib.noise.cells`` is ``noise/cells.py`` in a
library folder: each folder in ``$TOAST_LIB_PATH`` (separated by ``os.pathsep``), then
``~/.config/toast/lib``. Inside Blender, the add-on looks for a Text named after the library
first (see ``blender_addon.py``).
"""

import os
from pathlib import Path

from .compiler import LIB_PACKAGE


def library_dirs():
    dirs = [Path(p) for p in os.environ.get("TOAST_LIB_PATH", "").split(os.pathsep) if p]
    dirs.append(Path.home() / ".config" / "toast" / "lib")
    return dirs


def file_resolver(module):
    """Source of library ``module`` ("toast_lib.x.y") from the library folders, or None."""
    parts = module.split(".")
    if parts[0] != LIB_PACKAGE or len(parts) < 2:
        return None
    for d in library_dirs():
        path = d.joinpath(*parts[1:]).with_suffix(".py")
        if path.is_file():
            return path.read_text()
    return None
