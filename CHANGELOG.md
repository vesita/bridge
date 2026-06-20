# 更新日志 — Bridge (MMD PMX → glTF 自动转换器)

## [Unreleased]

### 修复

#### 1. GLB 导出时模型默认缩放被重置
- **问题**: GLTF 导出参数 `export_apply=True` 会将模型初始缩放烘焙到网格，导致导出后模型大小异常（缩放比例丢失）。
- **原因**: `_export.py` 中 `export_apply` 默认为 `True`，应用变换后模型的 0.085 缩放被烘焙进顶点坐标。
- **修复**: 将 `_GLTF_EXPORT_PARAMS` 中 `export_apply` 改为 `False`，保留原始变换结构。
- **涉及文件**: `src/bridge/_export.py`

#### 2. Blender 5.x `surface_render_method` 枚举错误
- **问题**: 每个材质转换时打印错误 `[MMD Exporter] blend mode設定に失敗: xxx / Error: 'OPAQUE' not in ('DITHERED', 'BLENDED')`。
- **原因**: Blender 5.x 中 `surface_render_method` 枚举不再包含 `"OPAQUE"`，仅支持 `DITHERED` 和 `BLENDED`。
- **修复**: 当 `use_alpha=False`（不透明材质）时跳过设置 `surface_render_method`（不透明是默认值），仅在需要透明时设置。
- **涉及文件**: `src/bridge/_materials.py` — `_set_blend_mode()`

#### 3. 面部多边形边缘可见（平滑着色不生效）
- **问题**: GLTF 模型中面部可见多边形三角面边缘折痕。
- **原因**: mmd_tools 导入 PMX 时在网格上保存了自定义法线（custom normals），即使设置了 `poly.use_smooth = True`，GLTF 导出器仍使用原始自定义法线而非重新计算的平滑法线。
- **修复**: 新增 `apply_smooth_shading()` 函数，采用三重策略确保法线正确：
  1. `bpy.ops.object.shade_smooth()` — Blender 标准操作符
  2. 进入编辑模式调用 `customdata_custom_splitnormals_clear()` 清除自定义法线数据层
  3. 回退方案：`mesh.free_normals_split()`
- **涉及文件**: `src/bridge/blender_runner.py` — 新增 `apply_smooth_shading()`，在"重命名骨骼"之后、"导出"之前调用

#### 4. `UnboundLocalError`：`color_source` 未初始化
- **问题**: 材质没有纹理时 `_build_principled_material()` 中 `color_source` 被引用前未赋值。
- **修复**: 在函数入口处初始化 `color_source = None`，并在引用时加 `if color_source is not None:` 守卫。
- **涉及文件**: `src/bridge/_materials.py` — `_build_principled_material()`

#### 5. 球面纹理检测不到（mmd_tools 内部节点）
- **问题**: 所有材质的球面纹理都检测不到（`node_sphere=False`），因为 mmd_tools 将球面纹理存储在 `mmd_shader` 自定义节点组内部，而非顶层节点。
- **修复**: 在 `_extract_images_from_nodes()` 中增加第 3 步：扫描 `mmd_shader.node_tree` 内部的所有 `TEX_IMAGE` 节点。如果命名没有区分出球面但恰好有 2 张纹理，默认第一张为基础纹理、第二张为球面纹理。
- **涉及文件**: `src/bridge/_materials.py` — `_extract_images_from_nodes()`

#### 6. GLTF 导出器从磁盘读取原始纹理覆盖像素级修改
- **问题**: `_bake_sphere_into_base()` 在像素级别混合球面纹理到基础纹理后，GLTF 导出器可能从磁盘读取原始文件，覆盖内存中的修改。
- **修复**: 像素修改后调用 `image.pack()` 将图像数据打包到 .blend 文件内，确保导出器使用修改后的数据。
- **涉及文件**: `src/bridge/_materials.py` — `_bake_sphere_into_base()`

#### 7. DEBUG 打印被 CLI 过滤器静默丢弃
- **问题**: `cli.py` 的 stdout 过滤器只放行带 `[convert]`、`Error`、`ERROR`、`Warning`、`Saved` 标签的行，导致调试输出看不见。
- **修复**: 将 `[MMD Exporter]` 加入过滤器白名单标签。
- **涉及文件**: `src/bridge/cli.py` — `run_conversion()`

#### 8. 球面纹理类型判断逻辑不完善
- **问题**: 从 `mmd_material.sphere_texture_type` 获取的球面类型（MULTIPLY/ADD）在元数据缺失时没有合理的默认行为。
- **修复**: 
  - 当节点树中存在球面纹理但类型未设置时，默认 `is_mult_sphere = True`
  - 当从文件路径加载球面纹理时，同样默认 `is_mult_sphere = True`
  - `AUTO` 模式：MULTIPLY 球面应用到所有材质，ADD 球面仅应用到眼球材质
- **涉及文件**: `src/bridge/_materials.py` — `MMD_OT_ConvertMaterials.execute()`

#### 9. 纹理未找到时 `by_basename` 查找逻辑错误
- **问题**: `_find_or_load_image()` 中 `by_basename` 保存的是单张图片而非列表，且 `get()` 方法返回的是 `img` 对象而非可用的图片引用。
- **修复**: `_build_image_cache()` 中改用 `setdefault(basename, []).append(img)` 构建列表，`_find_or_load_image()` 中返回 `matches[0]`。
- **涉及文件**: `src/bridge/_materials.py`

#### 10. `PMX_DIR` 未传递给纹理搜索路径
- **问题**: PMX 文件所在目录未加入纹理搜索路径，导致纹理查找失败。
- **修复**: 新增 `PMX_DIR` 全局变量，在 `blender_runner.py` 中导入 PMX 后设置，`_get_model_search_dirs()` 将其加入搜索目录列表。
- **涉及文件**: `src/bridge/_materials.py`、`src/bridge/blender_runner.py`

#### 11. CLI 缺少 `--sphere-mode` 和 `--apply-transforms` 参数
- **问题**: CLI 没有暴露球面模式和变换应用参数给用户。
- **修复**: 
  - 新增 `--sphere-mode` 参数（支持 `NONE`/`AUTO`/`ALL`，默认 `AUTO`）
  - 新增 `--apply-transforms` 参数
  - 参数传递到 Blender 子进程
- **涉及文件**: `src/bridge/cli.py`

#### 12. 纹理 Alpha 通道未连接到 Principled BSDF
- **问题**: MMD 发型等纹理使用 Alpha 通道裁剪形状，透明区域的 RGB 为黑色。代码仅设置了材质级别的 `alpha` 默认值，没有将纹理的 Alpha 输出连接到 BSDF 的 Alpha 输入，导致黑色背景显示。
- **修复**: 创建纹理节点后，检测纹理是否有透明度（`_texture_has_transparency()`），如果有则将 Alpha 输出连接到 BSDF 的 Alpha 输入，并将混合模式设为 `DITHERED`（裁剪模式）。
- **涉及文件**: `src/bridge/_materials.py` — `_build_principled_material()`

#### 13. 球面纹理不支持加法模式（SubTexture）
- **问题**: `sphere_texture_type=2`（加法/SubTexture）的球面纹理被忽略，模型偏暗或丢失光泽。
- **原因**: `_extract_images_from_nodes()` 只识别了类型 `"1"`/`"MULT"`，未处理 `"2"`/`"ADD"`。
- **修复**: 增加 `is_add_sphere` 判断，加法球面使用 `blend_type="ADD"` 混合。
- **涉及文件**: `src/bridge/_materials.py` — `_extract_images_from_nodes()`, `_build_principled_material()`

#### 14. 多模型转换纹理错乱（`IMAGE_CACHE` 全局污染）
- **问题**: 同一 Blender 会话转换多个模型时，不同目录的同名纹理互相覆盖。
- **原因**: `by_basename` 缓存在 `IMAGE_CACHE` 为单值字典，同文件名后加载的覆盖前者。
- **修复**: `by_basename` 改为 `dict[str, list]` 结构，保留所有同名文件路径；回退时取第一个。
- **涉及文件**: `src/bridge/_materials.py` — `_build_image_cache()`, `_find_or_load_image()`

#### 15. 无头模式纹理搜索失败
- **问题**: Blender headless 模式中 `bpy.data.filepath` 为空，`_get_model_search_dirs()` 找不到 PMX 附近纹理。
- **修复**: 新增 `PMX_DIR` 模块变量；`blender_runner.py` 导入 PMX 后设置 `PMX_DIR`；`_get_model_search_dirs()` 返回 PMX 同目录。
- **涉及文件**: `src/bridge/_materials.py`, `src/bridge/blender_runner.py`

#### 16. CLI 错误回显丢回溯
- **问题**: Blender 内部异常的回溯未含 `[convert]`/`Error` 标签，被 stdout 过滤丢掉，用户看不到错误详情。
- **修复**: 退出码非零时打印完整输出；成功时保持原有过滤。
- **涉及文件**: `src/bridge/cli.py`

#### 17. CLI 缺少 `--apply-transforms` 参数
- **问题**: `apply_transforms` 未暴露给 CLI 用户，watch 模式也未传递该参数。
- **修复**: 新增 `--apply-transforms` CLI 参数；watch 模式调用 `run_conversion()` 时传入。
- **涉及文件**: `src/bridge/cli.py`

### 改进

- **代码注释全面中文化**: 所有 Python 文件的注释、文档字符串、UI 提示文本从日文/英文改为中文。
- **移除调试打印**: 清理 `[convert] DEBUG` 等调试输出。
- **`__main__.py` 改用 `sys.exit()`**: 确保退出码正确传递。

---

## [a513a6a] — 2026-06-20

### 初始化
- 初始提交：Bridge — MMD (PMX) 自动转 glTF
