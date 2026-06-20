"""
MMD material conversion — detection, extraction, Principled BSDF builder.
"""

import os
import bpy
from bpy.props import EnumProperty, BoolProperty, FloatProperty
from bpy.types import Operator

_BLENDER_VERSION = bpy.app.version

IMAGE_CACHE = {}

# ambient（环境色）叠加到 Base Color 时的默认强度（0.0〜1.0）。
# 0 表示不叠加（原始纹理颜色）。仅在需要让眉毛等更接近 MMD 亮色时才
# 在 Step1 的滑块中调高。调过高会使整体发白。
AMBIENT_STRENGTH = 0.0
PMX_DIR = ""


# ============================================================
# 通用工具函数
# ============================================================

def _normalize_path(filepath):
    if not filepath:
        return ""
    return os.path.normcase(os.path.normpath(filepath.replace("\\", "/")))


def _safe_abspath(filepath):
    if not filepath:
        return ""
    try:
        return bpy.path.abspath(filepath)
    except Exception:
        return filepath


def _set_blend_mode(mat, use_alpha, clip=False):
    """
    设置材质的透明模式。
    use_alpha=False: 不透明（OPAQUE）
    use_alpha=True, clip=True : 阿尔法裁剪（二值透明，用于眉毛等）
    use_alpha=True, clip=False: 半透明混合（用于镜头等）

    裁剪模式不会产生点状透光，适合透明纹理（眉毛、睫毛）。
    glTF 导出时，裁剪对应 alphaMode:MASK，混合对应 BLEND。
    """
    try:
        if _BLENDER_VERSION < (4, 2, 0):
            if not use_alpha:
                mat.blend_method = "OPAQUE"
            elif clip:
                mat.blend_method = "CLIP"
            else:
                mat.blend_method = "BLEND"
            if hasattr(mat, "shadow_method"):
                mat.shadow_method = "CLIP" if use_alpha else "OPAQUE"
        else:
            # OPAQUE 是默认值（Blender 5.x 的枚举中可能不包含 OPAQUE）
            if use_alpha and hasattr(mat, "surface_render_method"):
                mat.surface_render_method = "DITHERED" if clip else "BLENDED"
    except Exception as e:
        print(f"[MMD Exporter] blend mode設定に失敗: {mat.name} / {e}")


def _build_image_cache():
    IMAGE_CACHE.clear()
    by_basename = {}

    for img in bpy.data.images:
        if img.source != "FILE":
            continue

        abs_path = _safe_abspath(img.filepath)
        norm = _normalize_path(abs_path)

        if norm:
            IMAGE_CACHE[norm] = img

        basename = os.path.normcase(
            os.path.basename(img.filepath.replace("\\", "/"))
        )

        if basename:
            by_basename.setdefault(basename, []).append(img)

    return by_basename


def _find_or_load_image(filepath, by_basename=None, search_dirs=None):
    if not filepath:
        return None

    search_dirs = search_dirs or []
    candidates = []

    abs_path = _safe_abspath(filepath)
    candidates.append(abs_path)

    basename = os.path.basename(filepath.replace("\\", "/"))

    for directory in search_dirs:
        if directory and basename:
            candidates.append(os.path.join(directory, basename))
            candidates.append(os.path.join(directory, filepath))

    for candidate in candidates:
        norm = _normalize_path(candidate)

        if not norm:
            continue

        if norm in IMAGE_CACHE:
            return IMAGE_CACHE[norm]

        if os.path.exists(candidate):
            try:
                img = bpy.data.images.load(candidate, check_existing=True)
                IMAGE_CACHE[norm] = img
                return img
            except Exception as e:
                print(f"[MMD Exporter] 画像読み込み失敗: {candidate} / {e}")

    if by_basename and basename:
        matches = by_basename.get(os.path.normcase(basename))
        if matches:
            return matches[0]

    return None


def _get_model_search_dirs():
    dirs = []

    if bpy.data.filepath:
        base = os.path.dirname(bpy.data.filepath)
        dirs.append(base)
        dirs.append(os.path.join(base, "textures"))
        dirs.append(os.path.join(base, "Textures"))
        dirs.append(os.path.join(base, "texture"))
        dirs.append(os.path.join(base, "Texture"))

    if PMX_DIR:
        dirs.append(PMX_DIR)
        dirs.append(os.path.join(PMX_DIR, "textures"))
        dirs.append(os.path.join(PMX_DIR, "Textures"))

    return dirs


def _get_principled_socket(node, names):
    for name in names:
        if name in node.inputs:
            return node.inputs[name]
    return None


def _link_if_possible(tree, output_socket, input_socket):
    if output_socket and input_socket:
        tree.links.new(output_socket, input_socket)


# ============================================================
# MMD 材质检测
# ============================================================

def _is_mmd_material(mat):
    """
    判断是否为需要转换的 MMD 材质。
    """
    if mat.name.startswith("mmd_edge."):
        return False

    mmd_mat = getattr(mat, "mmd_material", None)
    if mmd_mat is None:
        return False

    if not mat.use_nodes or mat.node_tree is None:
        return False

    nodes = mat.node_tree.nodes

    if nodes.get("mmd_shader") is not None:
        return True

    has_principled = any(n.type == "BSDF_PRINCIPLED" for n in nodes)
    if not has_principled:
        return True

    return False


# ============================================================
# MMD 材质信息提取
# ============================================================

_PALE_CACHE = {}

_EYE_KEYWORDS = (
    "eye", "iris", "pupil", "hitomi", "目", "瞳", "眼", "白目", "黒目",
    "eyeball", "eyewhite", "sirome", "kurome",
)


def _looks_like_eye_material(mat, base_image):
    names = [mat.name.lower()]
    if base_image is not None:
        names.append(base_image.name.lower())
        try:
            names.append(base_image.filepath.lower())
        except Exception:
            pass

    for n in names:
        for kw in _EYE_KEYWORDS:
            if kw in n:
                return True
    return False


def _is_pale_base_image(image, threshold=0.75):
    if image is None:
        return False

    key = image.name
    if key in _PALE_CACHE:
        return _PALE_CACHE[key]

    result = False
    try:
        if image.has_data and len(image.pixels) >= 4:
            import numpy as np
            px = np.array(image.pixels[:], dtype=np.float32)
            rgb = px.reshape(-1, 4)[:, :3]
            mean_val = float(rgb.mean())
            result = mean_val >= threshold
    except Exception:
        result = False

    _PALE_CACHE[key] = result
    return result


_ALPHA_CACHE = {}


def _texture_has_transparency(image, threshold=0.5):
    if image is None:
        return False

    key = image.name
    if key in _ALPHA_CACHE:
        return _ALPHA_CACHE[key]

    result = False
    try:
        if image.has_data and getattr(image, "channels", 0) == 4 and len(image.pixels) >= 4:
            import numpy as np
            px = np.array(image.pixels[:], dtype=np.float32)
            alpha = px.reshape(-1, 4)[:, 3]
            result = float(alpha.min()) < threshold
    except Exception:
        result = False

    _ALPHA_CACHE[key] = result
    return result


def _extract_images_from_nodes(mat):
    base_image = None
    sphere_image = None

    if not mat.use_nodes or mat.node_tree is None:
        return base_image, sphere_image

    nodes = mat.node_tree.nodes

    # 1) 先查找顶层命名的节点
    base_node = nodes.get("mmd_base_tex")
    if base_node and getattr(base_node, "image", None):
        candidate = base_node.image
        cand_name = candidate.name.lower()
        if not ("toon" in cand_name
                or cand_name.endswith(".spa")
                or cand_name.endswith(".sph")):
            base_image = candidate

    sphere_node = nodes.get("mmd_sphere_tex")
    if sphere_node and getattr(sphere_node, "image", None):
        sphere_image = sphere_node.image

    # 2) 扫描顶层所有 TEX_IMAGE 节点
    if base_image is None or sphere_image is None:
        sph_image_fallback = None
        candidates = []

        for node in nodes:
            if node.type != "TEX_IMAGE":
                continue
            img = getattr(node, "image", None)
            if not img:
                continue

            name_lower = node.name.lower()
            label_lower = (node.label or "").lower()
            img_name_lower = img.name.lower()

            is_toon = (
                "toon" in name_lower
                or "toon" in label_lower
                or "toon" in img_name_lower
            )
            is_sphere = (
                "sphere" in name_lower
                or "sphere" in label_lower
                or "_sph" in name_lower
                or "sphere" in img_name_lower
                or img_name_lower.endswith(".spa")
                or img_name_lower.endswith(".sph")
            )

            if is_toon:
                continue
            if is_sphere:
                sph_image_fallback = sph_image_fallback or img
                continue

            candidates.append(img)

        if candidates and base_image is None:
            base_image = candidates[0]

        if sphere_image is None:
            sphere_image = sph_image_fallback

    # 3) 如果还没找到，到 mmd_shader 节点组内部查找
    if base_image is None or sphere_image is None:
        mmd_shader = nodes.get("mmd_shader")
        if mmd_shader and hasattr(mmd_shader, "node_tree") and mmd_shader.node_tree:
            inside_bases = []
            inside_spheres = []
            for internal in mmd_shader.node_tree.nodes:
                if internal.type != "TEX_IMAGE":
                    continue
                img = getattr(internal, "image", None)
                if not img:
                    continue

                name_lower = internal.name.lower()
                img_name_lower = img.name.lower()

                # 跳过 toon
                if "toon" in name_lower or "toon" in img_name_lower:
                    continue

                is_sphere = (
                    "sphere" in name_lower
                    or "_sph" in name_lower
                    or "sph" in name_lower  # 更宽松匹配
                    or "sphere" in img_name_lower
                    or img_name_lower.endswith(".sph")
                    or img_name_lower.endswith(".spa")
                )

                if is_sphere:
                    inside_spheres.append(img)
                else:
                    inside_bases.append(img)

            # 如果命名没有区分出球面，但恰好有2张纹理 → 默认第一张为基础，第二张为球面
            if not inside_spheres and len(inside_bases) >= 2:
                # 取第一张为基础，其他为球面（常见mmd_tools布局）
                inside_spheres = inside_bases[1:]
                inside_bases = inside_bases[:1]

            if inside_spheres and sphere_image is None:
                sphere_image = inside_spheres[0]
            if inside_bases and base_image is None:
                base_image = inside_bases[0]

    if base_image is None:
        tex_node_names = [n.name for n in nodes if n.type == "TEX_IMAGE"]
        print(
            f"[MMD Exporter] '{mat.name}': 未找到纹理图像。"
            f" TEX_IMAGE节点={tex_node_names if tex_node_names else '无'}"
        )

    return base_image, sphere_image


def _extract_mmd_material_info(mat):
    diffuse = getattr(mat, "diffuse_color", (1.0, 1.0, 1.0, 1.0))
    alpha = diffuse[3] if len(diffuse) >= 4 else 1.0

    texture_path = ""
    sphere_path = ""
    sphere_texture_type = "0"
    is_double_sided = False
    ambient = (0.0, 0.0, 0.0)

    mmd_mat = getattr(mat, "mmd_material", None)

    if mmd_mat:
        if hasattr(mmd_mat, "diffuse_color"):
            dc = mmd_mat.diffuse_color
            if len(dc) >= 3:
                diffuse = (dc[0], dc[1], dc[2], alpha)

        if hasattr(mmd_mat, "alpha"):
            alpha = float(mmd_mat.alpha)
            diffuse = (diffuse[0], diffuse[1], diffuse[2], alpha)

        if hasattr(mmd_mat, "ambient_color"):
            ac = mmd_mat.ambient_color
            if len(ac) >= 3:
                ambient = (ac[0], ac[1], ac[2])

        for attr in ("texture", "texture_filepath", "texture_path"):
            if hasattr(mmd_mat, attr):
                value = getattr(mmd_mat, attr)
                if value and isinstance(value, str):
                    texture_path = value
                    break

        for attr in ("sphere_texture", "sphere_texture_filepath", "sphere_texture_path"):
            if hasattr(mmd_mat, attr):
                value = getattr(mmd_mat, attr)
                if value and isinstance(value, str):
                    sphere_path = value
                    break

        if hasattr(mmd_mat, "sphere_texture_type"):
            sphere_texture_type = str(getattr(mmd_mat, "sphere_texture_type", "0"))

        got_double = False
        for attr in ("is_double_sided", "double_sided"):
            if hasattr(mmd_mat, attr):
                try:
                    is_double_sided = bool(getattr(mmd_mat, attr))
                    got_double = True
                    break
                except Exception:
                    pass
        if not got_double:
            is_double_sided = not getattr(mat, "use_backface_culling", True)

    return diffuse, alpha, texture_path, sphere_path, sphere_texture_type, is_double_sided, ambient


# ============================================================
# 球面纹理烘焙到基础纹理（GLTF 兼容性）
# ============================================================

def _bake_sphere_into_base(base_image, sph_image, blend_type="MULTIPLY"):
    """将球面纹理烘焙到基础纹理中（为了 GLTF 导出兼容性）。

    MMD 的球面纹理使用摄像机空间法线作为 UV 坐标，GLTF 无法表示这种映射。
    此函数在像素级别将球面纹理预混合到基础纹理中，使得在任何 GLTF 查看器中
    都能看到球面纹理的效果。

    blend_type: "MULTIPLY"（脸部着色）或 "ADD"（眼睛高光）。
    直接修改 base_image 的像素数据（保留文件路径，确保 GLTF 导出器能读取）。
    """
    import numpy as np

    w, h = base_image.size
    sw, sh = sph_image.size

    # 获取基础纹理像素 (float32)
    base_px = np.array(base_image.pixels[:], dtype=np.float32).reshape(h, w, 4)

    # 获取球面纹理像素，尺寸不同时缩放到基础纹理大小
    if sw == w and sh == h:
        sph_px = np.array(sph_image.pixels[:], dtype=np.float32).reshape(h, w, 4)
    else:
        # 创建临时图像（Blender 自动处理插值缩放）
        temp = bpy.data.images.new("__bake_temp", sw, sh, alpha=True)
        temp.pixels[:] = sph_image.pixels[:]
        temp.scale(w, h)
        sph_px = np.array(temp.pixels[:], dtype=np.float32).reshape(h, w, 4)
        bpy.data.images.remove(temp)

    # 执行混合
    if blend_type == "MULTIPLY":
        base_px[:, :, :3] *= sph_px[:, :, :3]
    elif blend_type == "ADD":
        base_px[:, :, :3] += sph_px[:, :, :3]

    # 钳位到有效范围并写回原图
    np.clip(base_px[:, :, :3], 0.0, 1.0, out=base_px[:, :, :3])
    base_image.pixels[:] = base_px.ravel()
    # 打包到 .blend 文件内，防止 GLTF 导出时从磁盘读取原始文件覆盖修改
    base_image.pack()


# ============================================================
# Principled BSDF 材质构建
# ============================================================

def _build_principled_material(
    mat,
    image=None,
    diffuse=(1.0, 1.0, 1.0, 1.0),
    alpha=1.0,
    is_double_sided=False,
    sph_image=None,
    apply_sphere=False,
    force_double_sided=False,
    ambient=(0.0, 0.0, 0.0),
    ambient_strength=AMBIENT_STRENGTH,
    is_add_sphere=False,
):
    mat.use_nodes = True
    mat.diffuse_color = (diffuse[0], diffuse[1], diffuse[2], alpha)
    if force_double_sided:
        mat.use_backface_culling = False
    else:
        mat.use_backface_culling = not is_double_sided

    use_alpha = alpha < 0.999
    _set_blend_mode(mat, use_alpha, clip=False)

    tree = mat.node_tree
    tree.nodes.clear()

    output = tree.nodes.new(type="ShaderNodeOutputMaterial")
    output.location = (500, 0)

    bsdf = tree.nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.location = (250, 0)

    tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    base_color_socket = _get_principled_socket(bsdf, ["Base Color"])
    alpha_socket = _get_principled_socket(bsdf, ["Alpha"])
    roughness_socket = _get_principled_socket(bsdf, ["Roughness"])
    metallic_socket = _get_principled_socket(bsdf, ["Metallic"])

    if base_color_socket:
        br = min(1.0, diffuse[0] + ambient[0] * ambient_strength)
        bg = min(1.0, diffuse[1] + ambient[1] * ambient_strength)
        bb = min(1.0, diffuse[2] + ambient[2] * ambient_strength)
        base_color_socket.default_value = (br, bg, bb, alpha)

    if alpha_socket:
        alpha_socket.default_value = alpha

    if roughness_socket:
        roughness_socket.default_value = 0.6

    if metallic_socket:
        metallic_socket.default_value = 0.0

    color_source = None

    if image:
        tex = tree.nodes.new(type="ShaderNodeTexImage")
        tex.location = (-500, 100)
        tex.image = image

        try:
            if image.colorspace_settings.name not in ("sRGB", "Filmic sRGB"):
                image.colorspace_settings.name = "sRGB"
        except Exception:
            pass

        color_source = tex.outputs.get("Color")

        # MMD 发型等纹理使用 Alpha 通道裁剪形状，透明区域 RGB 为黑色。
        # 必须将纹理的 Alpha 输出连接到 BSDF 的 Alpha 输入，否则黑色背景会显示出来。
        tex_alpha = tex.outputs.get("Alpha")
        if tex_alpha and alpha_socket and _texture_has_transparency(image):
            tree.links.new(tex_alpha, alpha_socket)
            # 有透明度的纹理使用 CLIP（裁剪）模式，避免排序问题
            if _BLENDER_VERSION < (4, 2, 0):
                mat.blend_method = "CLIP"
            elif hasattr(mat, "surface_render_method"):
                try:
                    mat.surface_render_method = "DITHERED"
                except Exception:
                    pass

        if sph_image and apply_sphere:
            # 将球面纹理烘焙到基础纹理中（GLTF 兼容性）。
            # MMD 球面纹理使用摄像机空间法线作为 UV，GLTF 无法表示。
            # 改为在像素级别预混合（直接修改原图像素，保留文件路径）。
            blend_type = "ADD" if is_add_sphere else "MULTIPLY"
            print(f"[MMD Exporter] '{mat.name}': 球面烘焙中 ({blend_type}) ...")
            _bake_sphere_into_base(image, sph_image, blend_type=blend_type)

    if color_source is not None:
        if ambient and max(ambient) > 0.001 and ambient_strength > 0.001:
            add = tree.nodes.new(type="ShaderNodeMixRGB")
            add.location = (60, 200)
            add.blend_type = "ADD"
            add.inputs[0].default_value = 1.0
            ar = ambient[0] * ambient_strength
            ag = ambient[1] * ambient_strength
            ab = ambient[2] * ambient_strength
            try:
                add.inputs[2].default_value = (ar, ag, ab, 1.0)
            except Exception:
                add.inputs[2].default_value = (ar, ag, ab)
            _link_if_possible(tree, color_source, add.inputs[1])
            _link_if_possible(tree, add.outputs.get("Color"), base_color_socket)
        else:
            _link_if_possible(tree, color_source, base_color_socket)


# ============================================================
# 材质转换操作符
# ============================================================

class MMD_OT_ConvertMaterials(Operator):
    bl_idname = "mmd.convert_materials"
    bl_label = "マテリアルを変換"
    bl_description = "MMDマテリアルをPrincipled BSDFへ変換します（エッジ・変換済みはスキップ）"
    bl_options = {"REGISTER", "UNDO"}

    sphere_mode: EnumProperty(
        name="スフィアマップ",
        description="スフィアマップ（乗算）の適用方法",
        items=[
            ("NONE", "適用しない（推奨）", "スフィアを一切使わない。base画像のみ。glTF出力に最も安全"),
            ("AUTO", "自動", "MULTIPLY（乗算）球面を全マテリアルに適用（顔の輪郭を滑らかに）。ADD（加算）球面は眼球のみ"),
            ("ALL", "常に適用", "全マテリアルに適用。MMD本来寄りだが暗く濁る場合がある"),
        ],
        default="NONE",
    )

    force_double_sided: BoolProperty(
        name="全マテリアルを両面表示",
        description="MMD側の設定に関わらず全マテリアルを両面表示にする。"
                    "通常はオフ（MMDの元設定を尊重）。法線が直らず透ける場合のみオン",
        default=False,
    )

    ambient_strength: FloatProperty(
        name="環境色（明るさ）の強さ",
        description="MMDのambientをBase Colorに加算する強さ。"
                    "上げると眉などが明るく（金色寄り）になるが、上げすぎると全体が白っぽくなる。"
                    "通常は0（素直なテクスチャ色）。眉などをMMD寄りにしたい場合のみ上げる",
        default=0.0, min=0.0, max=1.0, step=1, precision=2,
    )

    def execute(self, context):
        by_basename = _build_image_cache()
        search_dirs = _get_model_search_dirs()
        _PALE_CACHE.clear()
        _ALPHA_CACHE.clear()

        converted = 0
        skipped = 0
        missing_textures = []

        for mat in bpy.data.materials:
            if not _is_mmd_material(mat):
                skipped += 1
                continue

            node_image, node_sphere = _extract_images_from_nodes(mat)
            diffuse, alpha, texture_path, sphere_path, sphere_texture_type, is_double_sided, ambient = (
                _extract_mmd_material_info(mat)
            )

            image = node_image
            sph_image = None

            if image is None and texture_path:
                image = _find_or_load_image(texture_path, by_basename=by_basename, search_dirs=search_dirs)
            if image is None and texture_path:
                missing_textures.append(texture_path)

            is_mult_sphere = sphere_texture_type in ("1", "MULT", "Multiply", "multiply")
            is_add_sphere = sphere_texture_type in ("2", "ADD", "Add", "add")
            if node_sphere is not None:
                sph_image = node_sphere
                # 节点树中确实存在球面纹理 → 如果类型未设置则默认 MULTIPLY
                if not is_mult_sphere and not is_add_sphere:
                    is_mult_sphere = True
            elif sphere_path:
                sph_image = _find_or_load_image(sphere_path, by_basename=by_basename, search_dirs=search_dirs)
                if sph_image and not is_mult_sphere and not is_add_sphere:
                    is_mult_sphere = True

            if self.sphere_mode == "ALL":
                apply_sphere = sph_image is not None
            elif self.sphere_mode == "NONE":
                apply_sphere = False
            else:
                # AUTO: MULTIPLY 球面纹理（脸部着色）应用到所有材质，
                #       ADD 球面纹理（高光）只应用到眼球材质。
                if sph_image is None:
                    apply_sphere = False
                elif is_mult_sphere:
                    apply_sphere = True
                    print(f"[MMD Exporter] '{mat.name}': MULT球面适用 (自动)")
                elif _looks_like_eye_material(mat, image) and _is_pale_base_image(image):
                    apply_sphere = True
                    print(f"[MMD Exporter] '{mat.name}': ADD球面适用 (眼球)")
                else:
                    apply_sphere = False
                    print(f"[MMD Exporter] '{mat.name}': 球面跳过 (AUTO未匹配)")

            _build_principled_material(
                mat, image=image, diffuse=diffuse, alpha=alpha,
                is_double_sided=is_double_sided, sph_image=sph_image,
                apply_sphere=apply_sphere, force_double_sided=self.force_double_sided,
                ambient=ambient, ambient_strength=self.ambient_strength,
                is_add_sphere=is_add_sphere,
            )
            converted += 1

        if missing_textures:
            for path in missing_textures[:10]:
                print(f"[MMD Exporter] 未加载纹理: {path}")
            self.report({"WARNING"}, f"材质转换完成: {converted}个 / 跳过: {skipped}个 / 未加载纹理: {len(missing_textures)}个")
        else:
            self.report({"INFO"}, f"材质转换完成: {converted}个 / 跳过: {skipped}个")

        return {"FINISHED"}


def _run_convert_materials(by_basename, search_dirs, sphere_mode="NONE",
                           force_double_sided=False,
                           ambient_strength=AMBIENT_STRENGTH):
    """
    不经过 bpy.ops 直接执行材质转换的内部函数。
    用于避免导出对话框的上下文问题。
    """
    _PALE_CACHE.clear()
    _ALPHA_CACHE.clear()

    for mat in bpy.data.materials:
        if not _is_mmd_material(mat):
            continue

        node_image, node_sphere = _extract_images_from_nodes(mat)
        diffuse, alpha, texture_path, sphere_path, sphere_texture_type, is_double_sided, ambient = (
            _extract_mmd_material_info(mat)
        )

        image = node_image
        sph_image = None

        if image is None and texture_path:
            image = _find_or_load_image(texture_path, by_basename=by_basename, search_dirs=search_dirs)

        is_mult_sphere = sphere_texture_type in ("1", "MULT", "Multiply", "multiply")
        is_add_sphere = sphere_texture_type in ("2", "ADD", "Add", "add")
        if node_sphere is not None:
            sph_image = node_sphere
            if not is_mult_sphere and not is_add_sphere:
                is_mult_sphere = True
        elif sphere_path:
            sph_image = _find_or_load_image(sphere_path, by_basename=by_basename, search_dirs=search_dirs)
            if sph_image and not is_mult_sphere and not is_add_sphere:
                is_mult_sphere = True

        if sphere_mode == "ALL":
            apply_sphere = sph_image is not None
        elif sphere_mode == "NONE":
            apply_sphere = False
        else:
            # AUTO: MULTIPLY 球面纹理（脸部着色）应用到所有材质，
            #       ADD 球面纹理（高光）只应用到眼球材质。
            if sph_image is None:
                apply_sphere = False
            elif is_mult_sphere:
                apply_sphere = True
            elif _looks_like_eye_material(mat, image) and _is_pale_base_image(image):
                apply_sphere = True
            else:
                apply_sphere = False

        _build_principled_material(
            mat, image=image, diffuse=diffuse, alpha=alpha,
            is_double_sided=is_double_sided, sph_image=sph_image,
            apply_sphere=apply_sphere, force_double_sided=force_double_sided,
            ambient=ambient, ambient_strength=ambient_strength,
            is_add_sphere=is_add_sphere,
        )
