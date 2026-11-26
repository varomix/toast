# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""The add-on's editor features in the fork, without a window: prints RESULT <json>.

  blender -b --factory-startup --enable-autoexec --python blender_ui_check.py -- <repo>
"""

import json
import sys

import bpy

REPO = sys.argv[sys.argv.index("--") + 1]
sys.path.insert(0, REPO)
import toast  # noqa: E402
from toast import blender_addon  # noqa: E402

toast.register()
result = {"templates": [t[0] for t in blender_addon.templates()]}

tree = bpy.data.node_groups.new("tree", "GeometryNodeTree")
node = tree.nodes.new("GeometryNodeToast")

# A template without a node editor: creates the text.
bpy.ops.toast.template(template="08_delete_downward_faces")
text = bpy.data.texts.get("toast_delete_downward_faces.py")
result["template_text"] = text is not None and "remove_face" in text.as_string()

# Errors point at a line of the node's text or of a library text.
node.text = bpy.data.texts.new("code")
node.text.write("x = 1\ny = noise(\n")
blender_addon.update_node(node, force=True)
loc = blender_addon.error_location(node)
result["syntax_error"] = [node.error, loc[0].name if loc else None, loc[1] if loc else None]

lib = bpy.data.texts.new("toast_lib.bad")
lib.write("def f(x):\n    return x +\n")
node.text.clear()
node.text.write("from toast_lib.bad import f\n@a = f(1.0)\n")
blender_addon.update_node(node, force=True)
loc = blender_addon.error_location(node)
result["library_error"] = [node.error, loc[0].name if loc else None, loc[1] if loc else None]

node.text.clear()
node.text.write("@a = 1.0\n")
blender_addon.update_node(node, force=True)
result["status"] = list(blender_addon._status.get(node.as_pointer(), ()))
blender_addon.update_node(node, force=True)
result["status_again"] = list(blender_addon._status.get(node.as_pointer(), ()))

# Auto Compile off: an edit is noted, not compiled, until a manual compile.
addon_prefs = bpy.context.preferences.addons["toast"].preferences
addon_prefs.auto_compile = False
before = node.source_hash
node.text.clear()
node.text.write("@a = 2.0\n")
blender_addon._tick(debounce=False)
auto_off = {"skipped": node.source_hash == before,
            "noted": node.as_pointer() in blender_addon._edited}
blender_addon.update_node(node, debounce=False, edits=True)  # What Ctrl+Enter does for the node.
auto_off["compiled_manually"] = node.source_hash != before and not blender_addon._edited
# A missing kernel is built even with Auto Compile off.
import os
os.remove(node.kernel_path)
node.text.clear()
node.text.write("@a = 3.0\n")
blender_addon._tick(debounce=False)
auto_off["missing_kernel_built"] = os.path.exists(node.kernel_path)
# The node's Compile button (auto compile still off).
node.text.clear()
node.text.write("@a = 5.0\n")
blender_addon._tick(debounce=False)
before = node.source_hash
bpy.ops.toast.compile_node(tree=tree.name, node=node.name)
auto_off["compile_button"] = node.source_hash != before
addon_prefs.auto_compile = True
before = node.source_hash
node.text.clear()
node.text.write("@a = 4.0\n")
blender_addon._tick(debounce=False)
auto_off["auto_on_compiles"] = node.source_hash != before
result["auto_compile"] = auto_off

prefs = bpy.context.preferences.addons.get("toast")
result["registered"] = {
    "panel": hasattr(bpy.types, "TEXT_PT_toast"),
    "menu": hasattr(bpy.types, "TOAST_MT_templates"),
    "text_templates_menu": blender_addon._draw_text_templates in bpy.types.TEXT_MT_templates._dyn_ui_initialize(),
    "icon": blender_addon._icons is not None and "toast" in blender_addon._icons,
    "text_menu": blender_addon._draw_text_menu in bpy.types.TEXT_MT_text._dyn_ui_initialize(),
    "text_header": blender_addon._draw_text_header in bpy.types.TEXT_HT_header._dyn_ui_initialize(),
}
print("RESULT " + json.dumps(result))
