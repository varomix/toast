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
import re
import sys
import time
import traceback
from pathlib import Path

import bpy

from .build import build, build_source, cache_dir
from .compiler import LIB_PACKAGE, collect_libraries
from .errors import ToastBuildError, ToastError
from .libraries import file_resolver, library_dirs
from .version import VERSION

NODE_IDNAME = "GeometryNodeToast"
# The node's Run Over items and the compiler's names.
RUN_OVER = {"POINTS": "points", "FACES": "faces", "EDGES": "edges", "CORNERS": "corners",
            "CURVES": "curves", "INSTANCES": "instances", "GEOMETRY": "geometry"}  # fmt: skip
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
# node pointer -> (state, detail): "ok", "cached", "error", shown in the Toast panels.
_status = {}
# screen pointer -> pointer of the Toast node whose code that screen's Text Editor last showed.
_followed = {}

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
# "text: line 3: message" or "text: toast_lib.shapes line 3: message"
ERROR_RE = re.compile(r"^(?P<text>.*?): (?:(?P<lib>toast_lib\.[\w.]+) )?line (?P<line>\d+): ")


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


def builtin_compiler_path():
    """Where the Toast node looks for the built-in kernel compiler (see `load_jit` in the fork)."""
    program_dir = os.path.dirname(bpy.app.binary_path)
    if sys.platform == "darwin":
        return os.path.join(program_dir, "..", "Resources", "lib", "libtoast_jit.dylib")
    return os.path.join(program_dir, "lib", "libtoast_jit.so")


def builtin_compiler_available():
    """True when this Blender has the built-in kernel compiler."""
    return os.path.exists(builtin_compiler_path())


def backend():
    """'builtin' or 'external': $TOAST_BACKEND, else the add-on preference (Automatic picks the
    built-in compiler when there is one)."""
    choice = os.environ.get("TOAST_BACKEND", "").lower()
    if not choice:
        addon = bpy.context.preferences.addons.get(__package__)
        choice = addon.preferences.backend.lower() if addon else "auto"
    if choice == "auto":
        return "builtin" if builtin_compiler_available() else "external"
    return choice


def _source_hash(source, run_over, libs):
    lib_part = "\0".join(f"{k}\0{v}" for k, v in sorted(libs.items()))
    data = f"{VERSION}\0{backend()}\0{run_over}\0{source}\0{lib_part}".encode()
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
    key = node.as_pointer()
    if not source.strip():
        _assign(node, signature="", kernel_path="", error="", source_hash=source_hash)
        _status[key] = ("empty", "")
        return
    if lib_error is not None:
        _assign(node, error=f"{text_name}: {lib_error}", source_hash=source_hash)
        _status[key] = ("error", "")
        return
    start = time.perf_counter()
    try:
        if backend() == "builtin":
            kernel = build_source(source, run_over, lib_resolver=lib_resolver)
        else:
            kernel = build(source, run_over, lib_resolver=lib_resolver)
    except ToastError as ex:
        # Keep the previous signature so sockets and their links survive while the code is
        # being edited; the error stops evaluation and shows on the node.
        _assign(node, error=f"{text_name}: {ex}", source_hash=source_hash)
        _status[key] = ("error", "")
        return
    except ToastBuildError as ex:
        print(f"Toast: {ex}")
        _assign(node, error="Toast internal compile error, see the console", source_hash=source_hash)
        _status[key] = ("error", "")
        return
    seconds = time.perf_counter() - start
    if kernel.cached:
        _status[key] = ("cached", "")
    elif backend() == "builtin":
        _status[key] = ("ok", f"translated in {seconds * 1000:.0f} ms, compiled by the built-in compiler")
    else:
        _status[key] = ("ok", f"compiled in {seconds:.2f} s")
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


def _prefs():
    addon = bpy.context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def _follow_active_nodes():
    """Show the active Toast node's code in the Text Editor of the same screen, when the active
    node changes (Follow Active Node preference)."""
    prefs = _prefs()
    if prefs is None or not prefs.follow_active_node:
        return
    wm = bpy.context.window_manager
    for window in wm.windows if wm else ():
        screen = window.screen
        node = None
        for area in screen.areas:
            if area.type == "NODE_EDITOR":
                tree = area.spaces.active.edit_tree
                active = tree.nodes.active if tree else None
                if active is not None and active.bl_idname == NODE_IDNAME and active.select:
                    node = active
                    break
        if node is None:
            continue
        key = screen.as_pointer()
        if _followed.get(key) == node.as_pointer():
            continue
        _followed[key] = node.as_pointer()
        if node.text is None:
            continue
        for area in screen.areas:
            if area.type == "TEXT_EDITOR" and area.spaces.active.text != node.text:
                area.spaces.active.text = node.text
                area.tag_redraw()
                break


def _tick(debounce=True):
    try:
        for node in list(_toast_nodes()):
            update_node(node, debounce=debounce)
        _follow_active_nodes()
    except Exception:
        traceback.print_exc()
    return POLL_SECONDS


@bpy.app.handlers.persistent
def _on_load(_file):
    _pending.clear()
    _status.clear()
    _followed.clear()
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


def _text_editor(context):
    """A Text Editor area on the current screen, or None."""
    if context.screen is None:
        return None
    for area in context.screen.areas:
        if area.type == "TEXT_EDITOR":
            return area
    return None


def _show_text(context, text, line=None):
    """Show `text` in a Text Editor, with the cursor on `line` (1-based). False without one."""
    area = _text_editor(context)
    if area is None:
        return False
    space = area.spaces.active
    space.text = text
    if line is not None:
        index = max(0, min(line - 1, len(text.lines) - 1))
        text.cursor_set(index, character=0)
        text.select_set(index, 0, index, len(text.lines[index].body))
        visible = max(1, space.visible_lines)
        space.top = max(0, index - visible // 3)
    area.tag_redraw()
    return True


def error_location(node):
    """(Text, line) of the node's error, or None. Errors in a library point at its Text."""
    m = ERROR_RE.match(node.error or "")
    if m is None:
        return None
    text = node.text
    if m.group("lib"):
        text = bpy.data.texts.get(m.group("lib")) or bpy.data.texts.get(m.group("lib") + ".py")
    if text is None:
        return None
    return text, int(m.group("line"))


def templates():
    """[(file stem, label, run over, description)] of the bundled starter code."""
    found = []
    for path in sorted(TEMPLATE_DIR.glob("*.py")):
        run_over, description = "POINTS", ""
        for line in path.read_text().splitlines()[:4]:
            if line.startswith("# Run Over:"):
                run_over = line.split(":", 1)[1].strip().upper().replace("FACE ", "")
            elif line.startswith("# ") and not description:
                description = line[2:].strip()
        label = path.stem.split("_", 1)[1].replace("_", " ").capitalize()
        found.append((path.stem, label, run_over, description))
    return found


def _template_items(_self, _context):
    return [(stem, label, desc) for stem, label, _run, desc in templates()]


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
        _show_text(context, text)
        return {"FINISHED"}


class TOAST_OT_template(bpy.types.Operator):
    """Create a text from a Toast template. In a node editor, the active Toast node uses it"""

    bl_idname = "toast.template"
    bl_label = "Toast Template"
    bl_options = {"REGISTER", "UNDO"}

    template: bpy.props.EnumProperty(name="Template", items=_template_items)

    def execute(self, context):
        info = next((t for t in templates() if t[0] == self.template), None)
        if info is None:
            return {"CANCELLED"}
        stem, label, run_over, _desc = info
        text = bpy.data.texts.new(f"toast_{stem.split('_', 1)[1]}.py")
        text.write((TEMPLATE_DIR / f"{stem}.py").read_text())
        text.cursor_set(0)
        node = _active_toast_node(context)
        if node is not None:
            node.text = text
            node.run_over = run_over
            update_node(node, force=True)
        _show_text(context, text)
        self.report({"INFO"}, f"Toast template: {label}")
        return {"FINISHED"}


class TOAST_MT_templates(bpy.types.Menu):
    bl_idname = "TOAST_MT_templates"
    bl_label = "Toast"

    def draw(self, context):
        layout = self.layout
        layout.operator_context = "EXEC_DEFAULT"
        for stem, label, run_over, desc in templates():
            op = layout.operator("toast.template", text=label)
            op.template = stem


def _draw_text_templates(self, context):
    self.layout.menu(TOAST_MT_templates.bl_idname)


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
        if _show_text(context, _active_toast_node(context).text):
            return {"FINISHED"}
        self.report({"WARNING"}, "Open a Text Editor to edit the code")
        return {"CANCELLED"}


def _nodes_using(text):
    return [n for n in _toast_nodes() if n.text == text]


class TOAST_OT_show_error(bpy.types.Operator):
    """Show the line of the Toast error in the Text Editor"""

    bl_idname = "toast.show_error"
    bl_label = "Go to Error"

    tree: bpy.props.StringProperty(options={"SKIP_SAVE"})
    node: bpy.props.StringProperty(options={"SKIP_SAVE"})

    def execute(self, context):
        tree = bpy.data.node_groups.get(self.tree)
        node = tree.nodes.get(self.node) if tree else None
        location = error_location(node) if node else None
        if location is None:
            self.report({"WARNING"}, "The error has no line to show")
            return {"CANCELLED"}
        if not _show_text(context, *location):
            self.report({"WARNING"}, "Open a Text Editor to see the error")
            return {"CANCELLED"}
        return {"FINISHED"}


def _draw_status(layout, node):
    """Compile state and error of a node, with a button to the error's line."""
    state, detail = _status.get(node.as_pointer(), ("", ""))
    if node.error:
        box = layout.box()
        box.alert = True
        for k, line in enumerate(node.error.splitlines() or [""]):
            box.label(text=line, icon="ERROR" if k == 0 else "BLANK1")
        if error_location(node) is not None:
            op = box.operator("toast.show_error", icon="TEXT")
            op.tree = node.id_data.name
            op.node = node.name
        return
    if node.as_pointer() in _pending:
        layout.label(text="Compiling when you stop typing...", icon="SORTTIME")
    elif state == "cached":
        layout.label(text="Up to date (compiled earlier)", icon="CHECKMARK")
    elif state == "ok":
        layout.label(text="Up to date", icon="CHECKMARK")
        if detail:
            layout.label(text=detail, icon="BLANK1")
    elif node.kernel_path:
        layout.label(text="Up to date", icon="CHECKMARK")
    elif node.text is None:
        layout.label(text="No code: pick a text or a template", icon="INFO")


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
        row.operator_menu_enum("toast.template", "template", text="Templates", icon="PRESET")
        row.operator("toast.compile", text="", icon="FILE_REFRESH")
        layout.prop(node, "run_over")
        prefs = _prefs()
        if prefs is not None:
            layout.prop(prefs, "follow_active_node")
        _draw_status(layout, node)
        if node.signature and not node.error:
            try:
                sig = json.loads(node.signature)
            except ValueError:
                return
            col = layout.column(align=True)
            for a in sig.get("attrs", []):
                if a.get("output"):
                    col.label(text=f"{a['type']} output: {a['name']}")
                    continue
                where = f" (input {a['input']})" if a["input"] else ""
                snap = ", snapshot" if a.get("snapshot") else ""
                col.label(text=f"{a['type']} @{a['name']}: {a['access']}{where}{snap}")
            if sig.get("uses", {}).get("cmd"):
                col.label(text="Changes topology")


class TEXT_PT_toast(bpy.types.Panel):
    """Toast status in the Text Editor sidebar, for texts used by Toast nodes."""

    bl_space_type = "TEXT_EDITOR"
    bl_region_type = "UI"
    bl_category = "Toast"
    bl_label = "Toast"

    @classmethod
    def poll(cls, context):
        text = context.space_data.text
        return text is not None and (bool(_nodes_using(text)) or text.name.startswith("toast_lib."))

    def draw(self, context):
        layout = self.layout
        text = context.space_data.text
        nodes = _nodes_using(text)
        if not nodes:
            layout.label(text="A Toast library", icon="TEXT")
            for node in _toast_nodes():
                loc = error_location(node)
                if loc is not None and loc[0] == text:
                    _draw_status(layout, node)
                    break
            return
        for node in nodes:
            box = layout.box()
            box.label(text=f"{node.id_data.name} > {node.name}", icon="NODE")
            box.label(text=f"Run Over: {node.bl_rna.properties['run_over'].enum_items[node.run_over].name}")
            _draw_status(box, node)
        layout.label(text="Don't press Run Script: Toast code", icon="INFO")
        layout.label(text="recompiles by itself.", icon="BLANK1")


class TOAST_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    backend: bpy.props.EnumProperty(
        name="Compiler",
        description="How Toast code becomes native code",
        items=(
            ("AUTO", "Automatic", "The built-in compiler when this Blender has one, else external"),
            ("BUILTIN", "Built-in", "Blender's built-in compiler (in memory, no installs needed)"),
            ("EXTERNAL", "External", "An installed C++ compiler: $TOAST_CXX, clang++ or g++"),
        ),
        default="AUTO",
    )
    follow_active_node: bpy.props.BoolProperty(
        name="Follow Active Node",
        description="When you select a Toast node, show its code in the Text Editor of the same "
        "window",
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "backend")
        layout.prop(self, "follow_active_node")
        layout.label(text=f"Built-in compiler: {'available' if builtin_compiler_available() else 'not in this Blender'}"
                     f", in use: {backend()}")
        layout.label(text=f"Toast {VERSION}. Kernel cache: {cache_dir()}")
        layout.label(text="Libraries (import toast_lib.<name>): a text named toast_lib.<name>, or")
        for d in library_dirs():
            layout.label(text=f"    {d}")
        layout.label(text="External compiler: $TOAST_CXX, else clang++, else g++")


CLASSES = (TOAST_OT_new_text, TOAST_OT_template, TOAST_MT_templates, TOAST_OT_compile,
           TOAST_OT_edit_text, TOAST_OT_show_error, NODE_PT_toast, TEXT_PT_toast,
           TOAST_AddonPreferences)  # fmt: skip


def register():
    # Safe to call twice: the add-on can be enabled by default and also registered by scripts.
    if getattr(bpy.types, NODE_PT_toast.__name__, None) is not None:
        return
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.TEXT_MT_templates.append(_draw_text_templates)
    bpy.app.handlers.load_post.append(_on_load)
    bpy.app.timers.register(_tick, first_interval=POLL_SECONDS, persistent=True)


def unregister():
    if getattr(bpy.types, NODE_PT_toast.__name__, None) is None:
        return
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    bpy.types.TEXT_MT_templates.remove(_draw_text_templates)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
