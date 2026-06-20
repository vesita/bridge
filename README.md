# Bridge — MMD (PMX) 自动转 glTF 工具

将 MMD 模型（`.pmx`）自动批量转换为 glTF Binary（`.glb`）格式，适用于 Unity、Unreal Engine 等游戏引擎。

## 快速开始

```bash
# 转换所有模型
uv run python build.py

# 转换指定模型
uv run python build.py 模型目录名
```

## 环境要求

- **Blender** 4.2+（推荐 5.x），需安装 [mmd_tools](https://github.com/UuuNyaa/blender_mmd_tools) 扩展
- **uv**（Python 包管理器）

## 目录结构

```
bridge/
├── build.py                    # 构建脚本 — 扫描输入目录并调用 Blender 转换
├── convert.py                  # Blender 转换脚本（在 Blender 内部执行）
├── mmd_to_gltf_exporter.py     # Blender 插件 — 材质转换、骨骼重命名、GLB 导出
├── pyproject.toml              # uv 项目配置
├── uv.lock                     # 依赖锁文件
├── data/
│   ├── inputs/                 # 输入目录 — 把你的 .pmx 模型放这里
│   │   └── 模型名/
│   │       ├── model.pmx
│   │       ├── texture1.png
│   │       └── ...
│   └── outputs/                # 输出目录 — 自动生成的 .glb 文件
│       └── 模型名/
│           └── model.glb
└── README.md
```

## 详细用法

### 基本使用

```bash
# 转换 data/inputs/ 下所有模型
uv run python build.py

# 只转换特定模型
uv run python build.py Melusine05_Mamere
```

### 指定 Blender 路径

工具会自动检测常见位置的 Blender，如果找不到或想用特定版本：

```bash
uv run python build.py --blender /usr/local/blender/blender
uv run python build.py -b /opt/blender-4.2/blender
```

### 监听模式

监控输入目录，新增 PMX 文件时自动转换：

```bash
uv run python build.py --watch
uv run python build.py -w -i 5   # 每 5 秒检测一次（默认 10 秒）
```

### 转换选项

```bash
# 控制球面贴图（Sphere Map）处理方式
uv run python build.py --sphere-mode AUTO

# 调整环境色强度（0.0~1.0，让眉毛等部位更亮）
uv run python build.py --ambient-strength 0.2

# 强制双面渲染（解决法线翻转导致的透面问题）
uv run python build.py --force-double-sided

# 组合使用
uv run python build.py 模型名 --sphere-mode NONE --ambient-strength 0.0
```

### `--sphere-mode` 说明

| 模式 | 效果 |
|---|---|
| `NONE`（默认） | 不使用球面贴图，最安全的 glTF 输出 |
| `AUTO` | 仅眼球材质（名称含 eye/瞳/目 且底色偏白）自动应用 |
| `ALL` | 所有材质都应用球面贴图（可能偏暗） |

## 转换流程

1. **导入 PMX** — 通过 mmd_tools 导入模型（网格、骨骼、表情）
2. **材质转换** — 将 MMD 特有材质转为 Principled BSDF（PBR 标准材质）
3. **骨骼重命名** — 日文骨骼名转英文（便于引擎识别）
4. **导出 GLB** — 输出 glTF Binary 2.0 格式，含骨骼动画和形态键

## 常见问题

**Q: Blender 找不到？**
```bash
uv run python build.py -b /实际路径/blender
```

**Q: 导出的模型在引擎里透面/反了？**
```bash
uv run python build.py --force-double-sided
```

**Q: 眉毛/眼睛颜色不对？**
```bash
# 尝试提高环境色强度
uv run python build.py --ambient-strength 0.15 --sphere-mode AUTO
```

## 许可证

MIT
