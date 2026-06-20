"""
Blender add-on: MMD → glTF Exporter.

Converts MMD materials to Principled BSDF, renames bones to English,
and exports as GLB. Thin entry point — logic lives in sibling _*.py modules.

Install via Blender Preferences → Add-ons → Install…
(select this file: src/bridge/addon.py)
or use in headless mode via blender_runner.py.
"""

# @ https://github.com/masaka1024/mmd-to-gltf-exporter

bl_info = {
    "name": "MMD to glTF Exporter",
    "author": "Custom Addon / revised by M365 Copilot",
    "version": (2, 5, 4),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > MMD Exporter",
    "description": "mmd_toolsで読み込んだMMDモデルをglTF/GLBに変換してエクスポートします",
    "category": "Import-Export",
}

import bpy

from ._materials import MMD_OT_ConvertMaterials
from ._bones import MMD_OT_RenameBones
from ._export import MMD_OT_ExportGLTF, MMD_PT_ExporterPanel

classes = [
    MMD_OT_ConvertMaterials,
    MMD_OT_RenameBones,
    MMD_OT_ExportGLTF,
    MMD_PT_ExporterPanel,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    print("MMD to glTF Exporter v2.5.4: 有効化されました")


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    print("MMD to glTF Exporter v2.5.4: 無効化されました")


if __name__ == "__main__":
    register()
