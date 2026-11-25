# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Blender side of Toast: keeps every Toast node's compiled kernel in sync with its code.

The fork's ``GeometryNodeToast`` never calls Python. This module watches the Text data-block of
each Toast node, compiles the code when it changes (debounced while typing), and writes the
result into the node: ``signature`` (sockets), ``kernel_path`` and ``error``. On load it also
rebuilds kernels missing from this machine's cache.

Compiling is safe on untrusted files: generated C++ only contains constants and identifiers
from the code. Loading and running a kernel is gated in C++ by Auto Run Python Scripts.
"""

import hashlib
import json
import os
import time
import traceback

import bpy

from .build import build, cache_dir
from .compiler import LIB_PACKAGE, collect_libraries
from .errors import ToastBuildError, ToastError
from .libraries import file_resolver, library_dirs
from .version import VERSION

NODE_IDNAME = "GeometryNodeToast"
RUN_OVER = {"POINTS": "points", "FACES": "faces", "EDGES": "edges", "CORNERS": "corners", "GEOMETRY": "geometry"}
POLL_SECONDS = 0.2
# Compile once the code has been unchanged this long, so typing doesn't compile every keystroke.
DEBOUNCE_SECONDS = 0.35

NEW_TEXT = '''# Toast: runs once per element (see Run Over on the node).
# @position, @normal... are attributes; param() makes a socket on the node.
amp = param("amp", 0.2)
n = noise(@position * param("freq", 4.0))
@position += @normal * n * amp
@height: float = n
'''

# node pointer -> (source hash, time first seen)
_pending = {}


def lib_resolver(module):
    """A Text named after the library ("toast_lib.x" or "toast_lib.x.py"), then library files."""
    for name in (module, module + ".py"):
        text = bpy.data.texts.get(name)
        if text is not None:
            return text.as_string()
    return file_resolver(module)


def _libraries(source):
    """Library sources the code imports; a ToastError if one is missing."""
    if LIB_PACKAGE not in source:
        return {}
    return collect_libraries(source, lib_resolver)


def _source_hash(source, run_over, libs):
    lib_part = "\0".join(f"{k}\0{v}" for k, v in sorted(libs.items()))
    data = f"{VERSION}\0{run_over}\0{source}\0{lib_part}".encode()
    return hashlib.sha256(data).hexdigest()[:32]


def _toast_nodes():
    for tree in bpy.data.node_groups:
        if tree.bl_idname != "GeometryNodeTree" or tree.library is not None:
            continue
        for node in tree.nodes:
            if node.bl_idname == NODE_IDNAME:
                yield node


def _assign(node, **values):
    """Set node properties, skipping unchanged ones: every set re-evaluates the tree."""
    for key, value in values.items():
        if getattr(node, key) != value:
            setattr(node, key, value)


def _compile_node(node, source, run_over, source_hash, lib_error=None):
    text_name = node.text.name if node.text else ""
    if not source.strip():
        _assign(node, signature="", kernel_path="", error="", source_hash=source_hash)
        return
    if lib_error is not None:
        _assign(node, error=f"{text_name}: {lib_error}", source_hash=source_hash)
        return
    try:
        kernel = build(source, run_over, lib_resolver=lib_resolver)
    except ToastError as ex:
        # Keep the previous signature so sockets and their links survive while the code is
        # being edited; the error stops evaluation and shows on the node.
        _assign(node, error=f"{text_name}: {ex}", source_hash=source_hash)
        return
    except ToastBuildError as ex:
        print(f"Toast: {ex}")
        _assign(node, error="Toast internal compile error, see the console", source_hash=source_hash)
        return
    signature = json.dumps(kernel.signature, sort_keys=True)
    # Signature first: it rebuilds the sockets before the new kernel runs.
    _assign(node, signature=signature)
    _assign(node, kernel_path=str(kernel.so_path), error="", source_hash=source_hash)


def update_node(node, force=False, debounce=True):
    """Compile ``node``'s code if it changed or its kernel is missing. Returns True if it did.

    ``debounce`` waits for edits to settle; off when nobody is typing (e.g. a file just loaded
    with kernels from an older Toast)."""
    source = node.text.as_string() if node.text else ""
    run_over = RUN_OVER.get(node.run_over, "points")
    lib_error = None
    try:
        libs = _libraries(source)
    except ToastError as ex:
        libs, lib_error = {}, ex
    # A missing library may appear later (a new text or file): hash the error so it is retried.
    h = _source_hash(source, run_over, libs) + ("" if lib_error is None else "!")
    stale = node.source_hash != h
    missing = bool(node.kernel_path) and not os.path.exists(node.kernel_path)
    if not (force or stale or missing):
        _pending.pop(node.as_pointer(), None)
        return False
    if stale and not force and debounce:
        # Debounce edits: wait until the source has been stable for a moment.
        key = node.as_pointer()
        seen = _pending.get(key)
        now = time.monotonic()
        if seen is None or seen[0] != h:
            _pending[key] = (h, now)
            if node.source_hash:  # Not the first compile: wait.
                return False
        elif now - seen[1] < DEBOUNCE_SECONDS:
            return False
    _pending.pop(node.as_pointer(), None)
    _compile_node(node, source, run_over, h, lib_error)
    return True


def _tick(debounce=True):
    try:
        for node in list(_toast_nodes()):
            update_node(node, debounce=debounce)
    except Exception:
        traceback.print_exc()
    return POLL_SECONDS


@bpy.app.handlers.persistent
def _on_load(_file):
    _pending.clear()
    _tick(debounce=False)


# ---------------------------------------------------------------------------- UI


def _active_toast_node(context):
    space = context.space_data
    if space is None or space.type != "NODE_EDITOR" or space.edit_tree is None:
        return None
    node = space.edit_tree.nodes.active
    if node is None or node.bl_idname != NODE_IDNAME:
        return None
    return node


class TOAST_OT_new_text(bpy.types.Operator):
    """Create a text with starter Toast code and use it in the active Toast node"""

    bl_idname = "toast.new_text"
    bl_label = "New Toast Code"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_toast_node(context) is not None

    def execute(self, context):
        node = _active_toast_node(context)
        text = bpy.data.texts.new("toast.py")
        text.write(NEW_TEXT)
        node.text = text
        update_node(node, force=True)
        return {"FINISHED"}


class TOAST_OT_compile(bpy.types.Operator):
    """Recompile the code of every Toast node now"""

    bl_idname = "toast.compile"
    bl_label = "Recompile Toast Code"

    def execute(self, context):
        count = 0
        for node in list(_toast_nodes()):
            update_node(node, force=True)
            count += 1
        self.report({"INFO"}, f"Compiled {count} Toast node(s)")
        return {"FINISHED"}


class TOAST_OT_edit_text(bpy.types.Operator):
    """Show the active Toast node's code in a Text Editor"""

    bl_idname = "toast.edit_text"
    bl_label = "Edit Code"

    @classmethod
    def poll(cls, context):
        node = _active_toast_node(context)
        return node is not None and node.text is not None

    def execute(self, context):
        node = _active_toast_node(context)
        for area in context.screen.areas:
            if area.type == "TEXT_EDITOR":
                area.spaces.active.text = node.text
                return {"FINISHED"}
        self.report({"WARNING"}, "Open a Text Editor to edit the code")
        return {"CANCELLED"}


class NODE_PT_toast(bpy.types.Panel):
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "Node"
    bl_label = "Toast"

    @classmethod
    def poll(cls, context):
        return _active_toast_node(context) is not None

    def draw(self, context):
        layout = self.layout
        node = _active_toast_node(context)
        layout.template_ID(node, "text", new="toast.new_text")
        row = layout.row(align=True)
        row.operator("toast.edit_text", icon="TEXT")
        row.operator("toast.compile", text="", icon="FILE_REFRESH")
        layout.prop(node, "run_over")

        if node.error:
            box = layout.box()
            box.alert = True
            for k, line in enumerate(node.error.splitlines() or [""]):
                box.label(text=line, icon="ERROR" if k == 0 else "BLANK1")
        if node.signature:
            try:
                sig = json.loads(node.signature)
            except ValueError:
                return
            col = layout.column(align=True)
            for a in sig.get("attrs", []):
                where = f" (input {a['input']})" if a["input"] else ""
                snap = ", snapshot" if a.get("snapshot") else ""
                col.label(text=f"{a['type']} @{a['name']}: {a['access']}{where}{snap}")
            if sig.get("uses", {}).get("cmd"):
                col.label(text="Changes topology")
        if node.kernel_path:
            layout.label(text=os.path.basename(node.kernel_path), icon="FILE_BLANK")


class TOAST_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    def draw(self, context):
        layout = self.layout
        layout.label(text=f"Toast {VERSION}. Kernel cache: {cache_dir()}")
        layout.label(text="Libraries (import toast_lib.<name>): a text named toast_lib.<name>, or")
        for d in library_dirs():
            layout.label(text=f"    {d}")
        layout.label(text="Compiler: $TOAST_CXX, else clang++, else g++")


CLASSES = (TOAST_OT_new_text, TOAST_OT_compile, TOAST_OT_edit_text, NODE_PT_toast,
           TOAST_AddonPreferences)  # fmt: skip


def register():
    # Safe to call twice: the add-on can be enabled by default and also registered by scripts.
    if getattr(bpy.types, NODE_PT_toast.__name__, None) is not None:
        return
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.app.handlers.load_post.append(_on_load)
    bpy.app.timers.register(_tick, first_interval=POLL_SECONDS, persistent=True)


def unregister():
    if getattr(bpy.types, NODE_PT_toast.__name__, None) is None:
        return
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
