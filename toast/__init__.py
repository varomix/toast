# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Toast: a Python-syntax kernel language for Blender geometry nodes, compiled to native code.

This package is the frontend. It has no Blender dependency, so it can be developed and tested
with plain Python (see ``harness.py``). The Blender add-on registration comes later.
"""

bl_info = {
    "name": "Toast",
    "author": "varomix",
    "version": (0, 22, 0),
    "blender": (5, 3, 0),
    "location": "Geometry Nodes > Add > Toast",
    "description": "Python-syntax kernels for the Toast geometry node, compiled to native code",
    "category": "Node",
}

from .build import Kernel, build  # noqa: E402
from .compiler import compile_source
from .errors import ToastBuildError, ToastError
from .version import ABI_VERSION, VERSION

def register():
    from . import blender_addon

    blender_addon.register()


def unregister():
    from . import blender_addon

    blender_addon.unregister()


__all__ = [
    "ABI_VERSION",
    "VERSION",
    "Kernel",
    "ToastBuildError",
    "ToastError",
    "build",
    "compile_source",
]
