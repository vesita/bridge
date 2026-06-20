"""
MMD → GLB export — pre-processing, export operator, sidebar panel.
"""

import bpy
from bpy.props import StringProperty, BoolProperty
from bpy.types import Operator, Panel
from bpy_extras.io_utils import ExportHelper

from ._materials import (
    _run_convert_materials,
    _build_image_cache,
    _get_model_search_dirs,
)

# export_apply を True にするとエクスポート時にトランスフォーム（回転・スケール）と
# モディファイアが適用され、面の向きが正しく出力される（裏返り防止）。
# MMDモデルは未適用の回転・スケールを持つことが多く、False だと裏返りが起きるため
# True をデフォルトとする。
_GLTF_EXPORT_PARAMS = {
    "export_format": "GLB",
    "use_visible": True,
    "export_apply": True,
    "export_yup": True,
    "export_texcoords": True,
    "export_normals": True,
    "export_materials": "EXPORT",
    "export_colors": True,
    "export_skins": True,
}

_GLTF_EXPORT_PARAMS_FALLBACK = {
    "export_format": "GLB",
    "use_visible": True,
    "export_apply": True,
    "export_yup": True,
    "export_materials": "EXPORT",
    "export_skins": True,
}


# ============================================================
# エクスポート前処理
# ============================================================

def _hide_mmd_internal_objects():
    hidden_states = []

    for obj in bpy.data.objects:
        if obj.name.startswith(".dummy_armature") or "mmd_bind" in obj.name:
            hidden_states.append((obj, obj.hide_viewport, obj.hide_render))
            obj.hide_viewport = True
            obj.hide_render = True

    print(f"[MMD Exporter] 内部オブジェクトを一時非表示: {len(hidden_states)}件")
    return hidden_states


def _restore_hidden_objects(hidden_states):
    for obj, hide_viewport, hide_render in hidden_states:
        try:
            obj.hide_viewport = hide_viewport
            obj.hide_render = hide_render
        except ReferenceError:
            pass


def _mute_sdef_shape_keys():
    muted_states = []

    for mesh in bpy.data.meshes:
        if not mesh.shape_keys:
            continue

        for key_block in mesh.shape_keys.key_blocks:
            if key_block.name.startswith("mmd_sdef_"):
                muted_states.append((key_block, key_block.mute))
                key_block.mute = True

    print(f"[MMD Exporter] SDEFシェイプキーを一時ミュート: {len(muted_states)}件")
    return muted_states


def _restore_sdef_shape_keys(muted_states):
    for key_block, mute in muted_states:
        try:
            key_block.mute = mute
        except ReferenceError:
            pass


# ============================================================
# GLBエクスポート
# ============================================================

class MMD_OT_ExportGLTF(Operator, ExportHelper):
    bl_idname = "mmd.export_gltf"
    bl_label = "GLBとしてエクスポート"
    bl_description = "Unity / Unreal Engine向けにGLBファイルを書き出します"

    filename_ext = ".glb"
    filter_glob: StringProperty(default="*.glb", options={"HIDDEN"})

    export_animations: BoolProperty(name="アニメーションを出力", default=True)
    export_morphs: BoolProperty(name="モーフを出力", default=True)
    convert_materials_before_export: BoolProperty(name="出力前にマテリアル変換", default=False)

    apply_transforms: BoolProperty(
        name="トランスフォーム/モディファイアを適用",
        description="エクスポート時に回転・スケール・モディファイアを適用する。"
                    "面の裏返りを防ぐため通常はオン。スキン変形に問題が出る場合はオフにする",
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "export_animations")
        layout.prop(self, "export_morphs")
        layout.prop(self, "apply_transforms")
        layout.prop(self, "convert_materials_before_export")

    def execute(self, context):
        filepath = self.filepath
        if not filepath.lower().endswith(".glb"):
            filepath += ".glb"

        if self.convert_materials_before_export:
            by_basename = _build_image_cache()
            search_dirs = _get_model_search_dirs()
            _run_convert_materials(by_basename, search_dirs)

        hidden_states = _hide_mmd_internal_objects()
        muted_states = _mute_sdef_shape_keys()

        try:
            params = dict(_GLTF_EXPORT_PARAMS)
            params["filepath"] = filepath
            params["export_morph"] = self.export_morphs
            params["export_animations"] = self.export_animations
            params["export_apply"] = self.apply_transforms

            try:
                bpy.ops.export_scene.gltf(**params)
            except TypeError:
                fallback_params = dict(_GLTF_EXPORT_PARAMS_FALLBACK)
                fallback_params["filepath"] = filepath
                fallback_params["export_morph"] = self.export_morphs
                fallback_params["export_animations"] = self.export_animations
                fallback_params["export_apply"] = self.apply_transforms
                bpy.ops.export_scene.gltf(**fallback_params)

        except Exception as e:
            self.report({"ERROR"}, f"GLBエクスポート失敗: {e}")
            return {"CANCELLED"}
        finally:
            _restore_sdef_shape_keys(muted_states)
            _restore_hidden_objects(hidden_states)

        self.report({"INFO"}, f"GLBエクスポート完了: {filepath}")
        return {"FINISHED"}


# ============================================================
# サイドバーパネル
# ============================================================

class MMD_PT_ExporterPanel(Panel):
    bl_label = "MMD → glTF Exporter"
    bl_idname = "MMD_PT_exporter"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MMD Exporter"

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)

        col.label(text="Step 1")
        col.operator("mmd.convert_materials", icon="MATERIAL")
        col.separator()

        col.label(text="Step 2")
        col.operator("mmd.rename_bones", icon="ARMATURE_DATA")
        col.separator()

        col.label(text="Step 3")
        col.operator("mmd.export_gltf", icon="EXPORT")
