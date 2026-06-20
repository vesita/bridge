# Bridge — MMD (PMX) 自动转 glTF 工具

将 MMD 模型（`.pmx`）自动批量转换为 glTF Binary（`.glb`）格式，适用于 Unity、Unreal Engine 等游戏引擎。

## 快速开始

```bash
# 转换所有模型（默认 scale=0.085，厘米→米转换）
uv run python main.py

# 转换指定模型
uv run python main.py 模型目录名

# 调整导入缩放
uv run python main.py --scale 0.01
```

## 环境要求

- **Blender** 4.2+（推荐 5.x），需安装 [mmd_tools](https://github.com/UuuNyaa/blender_mmd_tools) 扩展
- **uv**（Python 包管理器）

## 目录结构

```
bridge/
├── main.py                      # ★ 唯一入口：uv run python main.py
├── pyproject.toml               # uv 项目配置
├── uv.lock                      # 依赖锁文件
├── src/
│   └── bridge/                  # Python 包
│       ├── __init__.py          # 版本号 + PROJECT_ROOT 常量
│       ├── __main__.py          # 支持 python -m bridge
│       ├── cli.py               # CLI 构建调度（参数解析、发现模型、启动 Blender）
│       ├── blender_runner.py    # Blender 驱动（在 Blender 内部执行转换流程）
│       ├── addon.py             # Blender 插件入口（bl_info + 注册，可手动安装）
│       ├── _materials.py        # 材质转换：MMD→Principled BSDF、球面贴图、ambient
│       ├── _bones.py            # 骨骼重命名：日文→英文
│       └── _export.py           # GLB 导出：参数、预/后处理、面板
├── data/
│   ├── inputs/                  # 输入目录 — 把你的 .pmx 模型放这里
│   │   └── 模型名/
│   │       ├── model.pmx
│   │       ├── texture1.png
│   │       └── ...
│   └── outputs/                 # 输出目录 — 自动生成的 .glb 文件
│       └── 模型名/
│           └── model.glb
└── README.md
```

## 详细用法

### 3 种入口

```bash
# 方式一（推荐）：main.py
uv run python main.py

# 方式二：uv scripts 入口
uv run bridge

# 方式三：Python 模块
uv run python -m bridge
```

### 基本使用

```bash
# 转换 data/inputs/ 下所有模型
uv run python main.py

# 只转换特定模型
uv run python main.py Melusine05_Mamere
```

### 指定 Blender 路径

工具会自动检测常见位置的 Blender，如果找不到或想用特定版本：

```bash
uv run python main.py --blender /usr/local/blender/blender
uv run python main.py -b /opt/blender-4.2/blender
```

### 监听模式

监控输入目录，新增 PMX 文件时自动转换：

```bash
uv run python main.py --watch
```

### 缩放控制

MMD 模型以厘米为单位（1 unit ≈ 1 cm），而 glTF 以米为单位（1 unit = 1 meter），直接导出的模型在引擎里会放大 ~100 倍。

```bash
# 默认：0.085，150cm 的角色导出为 ~1.3m
uv run python main.py

# 真实的厘米→米转换
uv run python main.py --scale 0.01

# 保持 PMX 原始尺寸（150cm → 150m，适合不关心物理单位的情况）
uv run python main.py --scale 1.0
```

### Blender 插件安装

如果需要手动将插件安装到 Blender（例如在 Blender UI 中直接使用）：

1. Blender → Edit → Preferences → Add-ons
2. 点击 **Install…**，选择 `src/bridge/addon.py`
3. 勾选 "MMD to glTF Exporter" 启用

安装后在 3D 视口侧边栏（按 N 键）可以看到 **MMD Exporter** 标签页。

## 转换流程

```text
main.py → cli.py                                  [宿主 Python]
           │
           ├── 扫描 data/inputs/ 发现 .pmx 文件
           │
           └── 启动 blender --background --python blender_runner.py
                      │
                      ├─ Step 0: 加载 bridge.addon 插件
                      ├─ Step 1: 通过 mmd_tools 导入 PMX
                      ├─ Step 2: 材质转换 MMD → Principled BSDF (_materials.py)
                      ├─ Step 3: 骨骼重命名 日文 → 英文 (_bones.py)
                      └─ Step 4: 导出 GLB (_export.py)
```

## 内部模块说明

| 模块 | 职责 | 运行环境 |
| --- | --- | --- |
| `cli.py` | CLI 参数解析、模型发现、Blender 进程调度 | 宿主 Python |
| `blender_runner.py` | 在 Blender 内部编排导入→转换→导出流程 | Blender Python |
| `addon.py` | 插件入口，仅 `bl_info` + 导入注册 | Blender Python |
| `_materials.py` | MMD 材质检测、信息提取、PBR 节点树构建、球面贴图合成 | Blender Python |
| `_bones.py` | 日文→英文骨骼名映射 + 重命名操作器 | Blender Python |
| `_export.py` | GLB 导出参数、内部对象隐藏、SDEF 形态键静音 | Blender Python |

## 常见问题

**Q: Blender 找不到？**
```bash
uv run python main.py -b /实际路径/blender
```

**Q: 模型导入引擎后发现缩放不对（太大或太小）？**

这是因为 MMD 以厘米为单位，而 glTF 以米为单位。用 `--scale` 调整导入缩放：

```bash
# 默认 0.085 → 约 1.3m 高的角色
uv run python main.py

# 真实的厘米→米
uv run python main.py --scale 0.01

# 保留 PMX 原始数值
uv run python main.py --scale 1.0
```

**Q: 导出的模型在引擎里透面/反了？**

贴图方向问题通常是法线/切线数据兼容性导致的，尝试在 DCC 工具（Blender、Unity）里重新导入并调整法线设置。

**Q: 想从命令行直接导出 GLB（不经过 main.py）？**
```bash
blender --background --python src/bridge/blender_runner.py -- \
  --input_pmx 模型.pmx \
  --output_glb 输出.glb \
  --scale 0.085
```

## 许可证

MIT
