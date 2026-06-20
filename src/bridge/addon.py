"""
Blender 插件：MMD → glTF 导出器。

将 MMD 材质转换为 Principled BSDF，将骨骼重命名为英文，
并导出为 GLB。轻量入口 — 逻辑实现在同级 _*.py 模块中。

安装方式：Blender 偏好设置 → 插件 → 安装…
（选择本文件：src/bridge/addon.py）
或通过 blender_runner.py 在无头模式下使用。
"""

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
    print("MMD to glTF Exporter v2.5.4: 已启用")


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    print("MMD to glTF Exporter v2.5.4: 已禁用")


if __name__ == "__main__":
    register()
