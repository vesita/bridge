"""
MMD bone renaming — Japanese → English for glTF compatibility.
"""

import bpy
from bpy.types import Operator


_BONE_NAME_MAP = {
    "全ての親": "Root",
    "センター": "Center",
    "グルーブ": "Groove",
    "腰": "Waist",
    "上半身": "UpperBody",
    "上半身2": "UpperBody2",
    "首": "Neck",
    "頭": "Head",
    "両目": "Eyes",
    "左目": "Eye_L",
    "右目": "Eye_R",
    "左肩": "Shoulder_L",
    "左腕": "Arm_L",
    "左ひじ": "Elbow_L",
    "左手首": "Wrist_L",
    "右肩": "Shoulder_R",
    "右腕": "Arm_R",
    "右ひじ": "Elbow_R",
    "右手首": "Wrist_R",
    "左足": "Leg_L",
    "左ひざ": "Knee_L",
    "左足首": "Ankle_L",
    "左つま先": "Toe_L",
    "右足": "Leg_R",
    "右ひざ": "Knee_R",
    "右足首": "Ankle_R",
    "右つま先": "Toe_R",
    "左足ＩＫ": "LegIK_L",
    "右足ＩＫ": "LegIK_R",
    "左つま先ＩＫ": "ToeIK_L",
    "右つま先ＩＫ": "ToeIK_R",
}


def _iter_armatures():
    for obj in bpy.context.scene.objects:
        if obj.type == "ARMATURE":
            yield obj


def _unique_bone_name(armature_data, desired_name, current_bone=None):
    if not desired_name:
        return None

    if desired_name not in armature_data.bones:
        return desired_name

    if current_bone and current_bone.name == desired_name:
        return desired_name

    index = 1
    while True:
        candidate = f"{desired_name}.{index:03d}"
        if candidate not in armature_data.bones:
            return candidate
        index += 1


class MMD_OT_RenameBones(Operator):
    bl_idname = "mmd.rename_bones"
    bl_label = "ボーン名を英語に変換"
    bl_description = "mmd_toolsの英語名プロパティ、または簡易変換テーブルでボーン名を英語化します"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        armatures = list(_iter_armatures())

        if not armatures:
            self.report({"WARNING"}, "Armatureが見つかりません")
            return {"CANCELLED"}

        renamed = 0

        for arm_obj in armatures:
            for bone in arm_obj.data.bones:
                original_name = bone.name
                desired_name = None

                mmd_bone = getattr(bone, "mmd_bone", None)

                if mmd_bone:
                    for attr in ("name_e", "name_en", "english_name"):
                        if hasattr(mmd_bone, attr):
                            value = getattr(mmd_bone, attr)
                            if value:
                                desired_name = value
                                break

                if not desired_name:
                    desired_name = _BONE_NAME_MAP.get(original_name)

                if desired_name and desired_name != original_name:
                    new_name = _unique_bone_name(arm_obj.data, desired_name, current_bone=bone)
                    if new_name and new_name != original_name:
                        bone.name = new_name
                        renamed += 1

        self.report({"INFO"}, f"ボーン名変換完了: {renamed}件")
        return {"FINISHED"}
