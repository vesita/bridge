"""
MMD material conversion — detection, extraction, Principled BSDF builder.
"""

import os
import bpy
from bpy.props import EnumProperty, BoolProperty, FloatProperty
from bpy.types import Operator

_BLENDER_VERSION = bpy.app.version

IMAGE_CACHE = {}

# ambient（環境色）をBase Colorに加算する際の既定の強さ（0.0〜1.0）。
# 0 では加算なし（素直なテクスチャ色）。眉などをMMD寄りに明るくしたい場合のみ
# Step1のスライダーで上げる。上げすぎると全体が白っぽくなる。
AMBIENT_STRENGTH = 0.0


# ============================================================
# 共通ユーティリティ
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
    マテリアルの透過モードを設定する。
    use_alpha=False: 不透明（OPAQUE）
    use_alpha=True, clip=True : アルファクリップ（二値透過。眉毛など）
    use_alpha=True, clip=False: 半透明ブレンド（レンズなど）

    クリップは点描状に透けないので、透過テクスチャ（眉毛・まつ毛）に適する。
    glTFエクスポート時、クリップは alphaMode:MASK、ブレンドは BLEND になる。
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
            if hasattr(mat, "surface_render_method"):
                mat.surface_render_method = "BLENDED" if (use_alpha and not clip) else (
                    "DITHERED" if use_alpha else "OPAQUE"
                )
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

        if basename and basename not in by_basename:
            by_basename[basename] = img

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
        return by_basename.get(os.path.normcase(basename))

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
# MMDマテリアル判定
# ============================================================

def _is_mmd_material(mat):
    """
    変換対象のMMDマテリアルか判定する。
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
# MMDマテリアル情報取得
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

    if base_image is None:
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

        if candidates:
            base_image = candidates[0]

        if sphere_image is None:
            sphere_image = sph_image_fallback

    if base_image is None:
        tex_node_names = [n.name for n in nodes if n.type == "TEX_IMAGE"]
        print(
            f"[MMD Exporter] '{mat.name}': テクスチャ画像が見つかりません。"
            f" TEX_IMAGEノード={tex_node_names if tex_node_names else 'なし'}"
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
# Principled BSDFマテリアル構築
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

        if sph_image and apply_sphere:
            sph = tree.nodes.new(type="ShaderNodeTexImage")
            sph.location = (-300, -200)
            sph.image = sph_image
            try:
                sph.image.colorspace_settings.name = "sRGB"
            except Exception:
                pass

            geom = tree.nodes.new(type="ShaderNodeNewGeometry")
            geom.location = (-1100, -250)

            vec_xform = tree.nodes.new(type="ShaderNodeVectorTransform")
            vec_xform.location = (-900, -250)
            vec_xform.vector_type = "NORMAL"
            vec_xform.convert_from = "WORLD"
            vec_xform.convert_to = "CAMERA"
            _link_if_possible(tree, geom.outputs.get("Normal"), vec_xform.inputs.get("Vector"))

            mad = tree.nodes.new(type="ShaderNodeVectorMath")
            mad.location = (-700, -250)
            mad.operation = "MULTIPLY_ADD"
            mad.inputs[1].default_value = (0.5, 0.5, 0.5)
            mad.inputs[2].default_value = (0.5, 0.5, 0.5)
            _link_if_possible(tree, vec_xform.outputs.get("Vector"), mad.inputs[0])
            _link_if_possible(tree, mad.outputs.get("Vector"), sph.inputs.get("Vector"))

            try:
                mix = tree.nodes.new(type="ShaderNodeMix")
                mix.location = (-50, 50)
                mix.data_type = "RGBA"
                mix.factor_mode = "UNIFORM"
                mix.blend_type = "MULTIPLY"
                if "Factor" in mix.inputs:
                    mix.inputs["Factor"].default_value = 1.0
                _link_if_possible(tree, tex.outputs.get("Color"), mix.inputs.get("A"))
                _link_if_possible(tree, sph.outputs.get("Color"), mix.inputs.get("B"))
                color_source = mix.outputs.get("Result")
            except Exception:
                mix = tree.nodes.new(type="ShaderNodeMixRGB")
                mix.location = (-50, 50)
                mix.blend_type = "MULTIPLY"
                mix.inputs[0].default_value = 1.0
                _link_if_possible(tree, tex.outputs.get("Color"), mix.inputs[1])
                _link_if_possible(tree, sph.outputs.get("Color"), mix.inputs[2])
                color_source = mix.outputs.get("Color")

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
# Material conversion operator
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
            ("AUTO", "自動（眼球のみ）", "眼球系マテリアル（名前にeye/目/瞳等を含み、base画像が白っぽい）にのみ適用"),
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
            if node_sphere is not None:
                sph_image = node_sphere
            elif sphere_path and is_mult_sphere:
                sph_image = _find_or_load_image(sphere_path, by_basename=by_basename, search_dirs=search_dirs)

            if self.sphere_mode == "ALL":
                apply_sphere = sph_image is not None
            elif self.sphere_mode == "NONE":
                apply_sphere = False
            else:
                apply_sphere = (
                    sph_image is not None
                    and _looks_like_eye_material(mat, image)
                    and _is_pale_base_image(image)
                )
                if apply_sphere:
                    print(f"[MMD Exporter] '{mat.name}': 眼球と判定しスフィア適用")

            _build_principled_material(
                mat, image=image, diffuse=diffuse, alpha=alpha,
                is_double_sided=is_double_sided, sph_image=sph_image,
                apply_sphere=apply_sphere, force_double_sided=self.force_double_sided,
                ambient=ambient, ambient_strength=self.ambient_strength,
            )
            converted += 1

        if missing_textures:
            for path in missing_textures[:10]:
                print(f"[MMD Exporter] 未検出テクスチャ: {path}")
            self.report({"WARNING"}, f"マテリアル変換完了: {converted}件 / スキップ: {skipped}件 / 未検出テクスチャ: {len(missing_textures)}件")
        else:
            self.report({"INFO"}, f"マテリアル変換完了: {converted}件 / スキップ: {skipped}件")

        return {"FINISHED"}


def _run_convert_materials(by_basename, search_dirs, sphere_mode="NONE",
                           force_double_sided=False,
                           ambient_strength=AMBIENT_STRENGTH):
    """
    bpy.ops を経由せずマテリアル変換を直接実行する内部関数。
    エクスポートダイアログのコンテキスト問題を回避するために使用。
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
        if node_sphere is not None:
            sph_image = node_sphere
        elif sphere_path and is_mult_sphere:
            sph_image = _find_or_load_image(sphere_path, by_basename=by_basename, search_dirs=search_dirs)

        if sphere_mode == "ALL":
            apply_sphere = sph_image is not None
        elif sphere_mode == "NONE":
            apply_sphere = False
        else:
            apply_sphere = (
                sph_image is not None
                and _looks_like_eye_material(mat, image)
                and _is_pale_base_image(image)
            )

        _build_principled_material(
            mat, image=image, diffuse=diffuse, alpha=alpha,
            is_double_sided=is_double_sided, sph_image=sph_image,
            apply_sphere=apply_sphere, force_double_sided=force_double_sided,
            ambient=ambient, ambient_strength=ambient_strength,
        )
