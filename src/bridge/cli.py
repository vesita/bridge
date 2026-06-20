#!/usr/bin/env -S uv run
"""
MMD → glTF 构建编排器。

扫描 data/inputs/{dir} 下的 .pmx 文件，使用 Blender 无头模式
将每个文件转换为 data/outputs/{dir}/{name}.glb。

用法:
  uv run python main.py                          # 转换所有模型
  uv run python main.py Melusine05_Mamere         # 按子目录名转换单个模型
  uv run python main.py --blender /path/to/blender  # 指定 Blender 可执行文件
  uv run python main.py --watch                    # 监视模式（轮询新模型）
  uv run python main.py --help                     # 显示完整帮助
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# ── 项目路径 ──────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
INPUTS_DIR = _PROJECT_ROOT / "data" / "inputs"
OUTPUTS_DIR = _PROJECT_ROOT / "data" / "outputs"
CONVERT_SCRIPT = _PROJECT_ROOT / "src" / "bridge" / "blender_runner.py"

# ── 默认 Blender 搜索路径 ──────────────────────────────
BLENDER_CANDIDATES = [
    # 标准 Linux 安装路径
    "/home/vesita/blender/blender-5.1.2-linux-x64/blender",
    "/usr/local/blender/blender",
    "/opt/blender/blender",
    # 常见 PATH 可见名称
    "blender",
]

# ── 转换默认值 ────────────────────────────────────────
DEFAULT_SCALE = 0.085


# ================================================================
# 辅助函数
# ================================================================

def find_blender(hint=None):
    """定位 Blender 可执行文件。优先级：--blender > 提示 > PATH > 候选列表。"""
    if hint:
        hint = shutil.which(hint) or hint
        if hint and os.path.isfile(hint):
            return hint

    for candidate in BLENDER_CANDIDATES:
        resolved = shutil.which(candidate) or candidate
        if resolved and os.path.isfile(resolved):
            return resolved

    return None


def discover_pmx_models(subdir=None):
    """
    返回 (model_name, pmx_path, output_dir, output_glb) 元组列表。
    如果指定了 subdir，只扫描 data/inputs/<subdir>/。
    """
    results = []

    if subdir:
        search = [INPUTS_DIR / subdir]
    else:
        search = sorted(INPUTS_DIR.iterdir()) if INPUTS_DIR.is_dir() else []

    for entry in search:
        if not entry.is_dir():
            continue

        pmx_files = sorted(entry.glob("*.pmx"))
        if not pmx_files:
            continue

        for pmx_path in pmx_files:
            model_name = pmx_path.stem
            rel_parent = entry.relative_to(INPUTS_DIR)
            out_dir = OUTPUTS_DIR / rel_parent
            out_glb = out_dir / f"{model_name}.glb"
            results.append((model_name, pmx_path, out_dir, out_glb))

    return results


def run_conversion(blender_path, pmx_path, output_glb, *,
                   scale=DEFAULT_SCALE, apply_transforms=False,
                   sphere_mode="AUTO"):
    """启动 Blender 无头模式，转换一个 PMX → GLB。"""
    cmd = [
        str(blender_path),
        "--background",
        "--python", str(CONVERT_SCRIPT),
        "--",
        "--input_pmx", str(pmx_path),
        "--output_glb", str(output_glb),
        "--scale", str(scale),
        "--sphere-mode", str(sphere_mode),
    ]
    if apply_transforms:
        cmd.append("--apply-transforms")

    print(f"  → blender {pmx_path.name} → {output_glb.name}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    ok = result.returncode == 0

    if ok:
        # 成功时仅输出过滤后的内容
        for line in result.stdout.splitlines():
            if any(tag in line for tag in ("[convert]", "[MMD Exporter]", "Error", "ERROR", "Warning", "Saved")):
                print(f"    {line.strip()}")
    else:
        # 失败时输出全部内容（不丢失回溯信息）
        for line in result.stdout.splitlines():
            print(f"    {line.strip()}")
        for line in result.stderr.splitlines():
            print(f"    [stderr] {line.strip()}", file=sys.stderr)

    return ok


# ================================================================
# 命令
# ================================================================

def cmd_build(args):
    """扫描并转换全部（或单个）模型。"""
    blender = find_blender(args.blender)
    if not blender:
        print("ERROR: Blender not found. Use --blender /path/to/blender to specify.")
        return 1

    print(f"Blender: {blender}")
    print(f"Inputs:  {INPUTS_DIR}")
    print(f"Outputs: {OUTPUTS_DIR}")
    print(f"Script:  {CONVERT_SCRIPT}")
    print()

    models = discover_pmx_models(args.model)
    if not models:
        print("No .pmx files found in", str(INPUTS_DIR / (args.model or "")))
        return 0

    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    success = 0
    failed = 0

    for model_name, pmx_path, out_dir, out_glb in models:
        out_dir.mkdir(parents=True, exist_ok=True)
        ok = run_conversion(
            blender, pmx_path, out_glb,
            scale=args.scale,
            apply_transforms=args.apply_transforms,
            sphere_mode=args.sphere_mode,
        )
        if ok:
            success += 1
        else:
            failed += 1
            print(f"  ❌ 失败: {pmx_path}")

    print()
    print(f"── 完成: {success} 个成功, {failed} 个失败 ──")
    return 0 if failed == 0 else 1


def cmd_watch(args):
    """监视新 PMX 模型并自动转换。"""
    blender = find_blender(args.blender)
    if not blender:
        print("ERROR: 未找到 Blender。请使用 --blender /path/to/blender 指定。")
        return 1

    print(f"正在监视 {INPUTS_DIR} 中的新模型（每 10 秒轮询）...")
    print("按 Ctrl+C 停止。\n")

    seen = {p for _, p, _, _ in discover_pmx_models()}

    try:
        while True:
            current = {p for _, p, _, _ in discover_pmx_models()}
            new = current - seen
            if new:
                for pmx_path in sorted(new):
                    model_name = pmx_path.stem
                    out_dir = OUTPUTS_DIR / pmx_path.parent.relative_to(INPUTS_DIR)
                    out_glb = out_dir / f"{model_name}.glb"
                    out_dir.mkdir(parents=True, exist_ok=True)
                    print(f"检测到新模型: {pmx_path}")
                    run_conversion(
                        blender, pmx_path, out_glb,
                        scale=args.scale,
                        apply_transforms=args.apply_transforms,
                    )
                seen = current
            time.sleep(10)
    except KeyboardInterrupt:
        print("\n监视已停止。")
    return 0


# ================================================================
# CLI 入口
# ================================================================

def main():
    parser = argparse.ArgumentParser(
        prog="bridge-build",
        description="MMD (PMX) → glTF 自动转换器（用于 Blender）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  uv run python main.py                          转换所有模型\n"
            "  uv run python main.py Melusine05_Mamere         转换单个模型\n"
            "  uv run python main.py -b /opt/blender/blender   指定 Blender 路径\n"
            "  uv run python main.py --watch                   监视新模型\n"
        ),
    )

    # 模型名称（可选位置参数）
    parser.add_argument(
        "model", nargs="?",
        help="data/inputs/ 中的子目录名（省略则转换所有模型）",
    )

    # 全局选项
    parser.add_argument(
        "-b", "--blender",
        help="Blender 可执行文件路径（省略则自动检测）",
    )
    parser.add_argument(
        "--scale", type=float, default=DEFAULT_SCALE,
        help="PMX 导入缩放系数。MMD 使用厘米（1 单位 ≈ 1 厘米），glTF 使用米。"
             "默认 0.085 可获得约 1.3 米的角色。使用 1.0 保持原始大小，0.01 做精确 cm→m。",
    )
    parser.add_argument(
        "--watch", "-w", action="store_true",
        help="监视模式：轮询新 PMX 文件并自动转换",
    )
    parser.add_argument(
        "--apply-transforms", action="store_true",
        help="导出前应用变换/修改器（将缩放/旋转烘焙到网格中）",
    )
    parser.add_argument(
        "--sphere-mode", choices=("NONE", "AUTO", "ALL"), default="AUTO",
        help="球面纹理应用模式: AUTO（默认，仅眼材质）、"
             "NONE（无球面）、ALL（始终应用）"
    )

    args = parser.parse_args()

    if args.watch:
        return cmd_watch(args)
    return cmd_build(args)


if __name__ == "__main__":
    sys.exit(main())
