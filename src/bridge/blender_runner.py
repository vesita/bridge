"""
MMD (PMX) → glTF 转换脚本，在 Blender 内部（无头模式）运行。

由 bridge.cli 调用。

用法（通过 cli）：
  blender --background --python src/bridge/blender_runner.py -- \\
    --input_pmx /path/to/model.pmx \\
    --output_glb /path/to/output.glb

"--" 后的参数由本脚本解析：
  --input_pmx       .pmx 文件的路径
  --output_glb      输出 .glb 文件的路径
  --scale           PMX 导入缩放比例（默认：0.085）
  --apply-transforms  将变换烘焙到网格后再导出
"""

import bpy
import os
import sys
from pathlib import Path

# Project root derived from this file's location: src/bridge/blender_runner.py
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ============================================================
# 参数解析（Blender 调用中 "--" 之后的参数）
# ============================================================

def parse_args(argv):
    """从 sys.argv（"--" 标记之后）解析 --key value 对。"""
    args = {
        "input_pmx": None,
        "output_glb": None,
        "apply_transforms": False,
        "scale": 0.085,
        "sphere_mode": "AUTO",
    }

    # Find the '--' separator
    try:
        idx = argv.index("--")
        raw = argv[idx + 1:]
    except (ValueError, IndexError):
        raw = []

    i = 0
    while i < len(raw):
        if raw[i] == "--input_pmx":
            args["input_pmx"] = raw[i + 1]
            i += 2
        elif raw[i] == "--output_glb":
            args["output_glb"] = raw[i + 1]
            i += 2
        elif raw[i] == "--apply-transforms":
            args["apply_transforms"] = True
            i += 1
        elif raw[i] == "--sphere-mode":
            args["sphere_mode"] = raw[i + 1]
            i += 2
        elif raw[i] == "--scale":
            args["scale"] = float(raw[i + 1])
            i += 2
        else:
            i += 1

    return args


# ============================================================
# 插件管理
# ============================================================

def log(msg):
    print(f"[convert] {msg}")


def find_addon_path():
    """定位 src/bridge/addon.py 插件模块。"""
    return str(_PROJECT_ROOT / "src" / "bridge" / "addon.py")


def install_and_enable_addon():
    """
    在 Blender 中注册 MMD → glTF 插件。

    将项目的 src/ 添加到 sys.path，然后直接导入 bridge.addon 模块，
    而不是将插件文件复制到 Blender 的插件目录（那样会破坏 src/ 布局）。
    """
    addon_path = find_addon_path()
    if not addon_path or not os.path.isfile(addon_path):
        log(f"ERROR: addon not found at {addon_path} — cannot enable")
        return False

    # 确保项目的 src/ 在 sys.path 中
    src_dir = str(_PROJECT_ROOT / "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    module_name = "bridge.addon"

    import importlib
    if module_name in sys.modules:
        mod = sys.modules[module_name]
        try:
            mod.unregister()
        except Exception:
            pass
        mod = importlib.reload(mod)
    else:
        mod = importlib.import_module(module_name)

    # 注册插件类
    try:
        if hasattr(mod, "register"):
            mod.register()
            log("Registered add-on: bridge.addon")
        return True
    except Exception as e:
        log(f"ERROR: Failed to register add-on '{module_name}': {e}")
        return False


# ============================================================
# 转换步骤
# ============================================================

def import_pmx(pmx_path, scale=0.085):
    """将 PMX 模型导入场景。"""
    log(f"导入 {pmx_path}（缩放={scale}）...")

    # 清空默认场景
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    bpy.ops.mmd_tools.import_model(
        filepath=pmx_path,
        types={"MESH", "ARMATURE", "PHYSICS", "DISPLAY", "MORPHS"},
        scale=scale,
    )
    log("Import done.")


def convert_materials(sphere_mode="NONE", force_double_sided=False, ambient_strength=0.0):
    """将 MMD 材质转换为 Principled BSDF。"""
    log(f"Converting materials (sphere={sphere_mode}, double_sided={force_double_sided}, ambient={ambient_strength}) ...")
    bpy.ops.mmd.convert_materials(
        sphere_mode=sphere_mode,
        force_double_sided=force_double_sided,
        ambient_strength=ambient_strength,
    )
    log("Material conversion done.")


def rename_bones():
    """重命名骨骼以保证 glTF 兼容性。"""
    log("重命名骨骼中 ...")
    bpy.ops.mmd.rename_bones()
    log("Bone rename done.")


def apply_smooth_shading():
    """将所有网格面设为平滑着色，并清除自定义法线，确保 GLTF 导出平滑法线。

    mmd_tools 导入 PMX 时会保留原始法线作为自定义法线（custom normals）。
    即使设置了 poly.use_smooth = True，GLTF 导出器仍会使用这些自定义法线，
    导致多边形边缘可见。必须清除自定义法线并强制 Blender 重新计算。
    """
    log("Applying smooth shading ...")
    count = 0

    bpy.ops.object.select_all(action="DESELECT")

    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue

        mesh = obj.data
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        # 方法 1: 使用 Blender 标准操作符（设置平滑 + 重算法线）
        try:
            bpy.ops.object.shade_smooth()
        except Exception:
            for poly in mesh.polygons:
                poly.use_smooth = True

        # 方法 2: 进入编辑模式清除自定义法线数据层（最彻底的方式）
        try:
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.customdata_custom_splitnormals_clear()
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except Exception:
                pass
            # 回退：直接清除
            try:
                if hasattr(mesh, "free_normals_split"):
                    mesh.free_normals_split()
            except Exception:
                pass

        obj.select_set(False)
        count += 1

    bpy.ops.object.select_all(action="DESELECT")
    log(f"Applied smooth shading to {count} meshes.")


def export_glb(output_path, export_animations=True, export_morphs=True, apply_transforms=False):
    """导出为 GLB。"""
    log(f"导出到 {output_path} ...")
    bpy.ops.mmd.export_gltf(
        filepath=output_path,
        export_animations=export_animations,
        export_morphs=export_morphs,
        apply_transforms=apply_transforms,
    )
    log(f"导出完毕: {output_path}")


# ============================================================
# 主入口
# ============================================================

def main():
    args = parse_args(sys.argv)

    input_pmx = args["input_pmx"]
    output_glb = args["output_glb"]

    if not input_pmx or not os.path.isfile(input_pmx):
        log(f"错误: --input_pmx 必填且文件必须存在: {input_pmx}")
        sys.exit(1)

    if not output_glb:
        log("错误: --output_glb 必填")
        sys.exit(1)

    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_glb), exist_ok=True)

    # Step 0: 安装并启用插件
    if not install_and_enable_addon():
        sys.exit(1)

    # Step 1: 导入 PMX
    import_pmx(input_pmx, scale=args["scale"])

    # 设置 PMX 目录供材质纹理搜索使用
    _pmx_dir = os.path.dirname(input_pmx)
    # 无法直接分配给导入的名称，通过模块属性设置
    import bridge._materials as _mat_mod
    _mat_mod.PMX_DIR = _pmx_dir

    # Step 2: 转换材质
    convert_materials(sphere_mode=args["sphere_mode"])

    # Step 3: 重命名骨骼
    rename_bones()

    # Step 3.5: 对所有网格应用平滑着色（修复可见的多边形边缘）
    apply_smooth_shading()

    # Step 4: 导出为 GLB
    export_glb(output_glb, apply_transforms=args["apply_transforms"])

    log("=== 转换完成 ===")


if __name__ == "__main__":
    main()
