#!/usr/bin/env -S uv run
"""
MMD → glTF build orchestrator.

Scans data/inputs/{dir} for .pmx files and converts each to
data/outputs/{dir}/{name}.glb using Blender headless.

Usage:
  uv run python main.py                          # Convert all models
  uv run python main.py Melusine05_Mamere         # Convert one model by subdir name
  uv run python main.py --blender /path/to/blender  # Use a specific Blender binary
  uv run python main.py --watch                    # Watch for new models (polling)
  uv run python main.py --help                     # Show full help
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# ── Project paths ──────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
INPUTS_DIR = _PROJECT_ROOT / "data" / "inputs"
OUTPUTS_DIR = _PROJECT_ROOT / "data" / "outputs"
CONVERT_SCRIPT = _PROJECT_ROOT / "src" / "bridge" / "blender_runner.py"

# ── Default Blender search paths ──────────────────────────────
BLENDER_CANDIDATES = [
    # Standard Linux installs
    "/home/vesita/blender/blender-5.1.2-linux-x64/blender",
    "/usr/local/blender/blender",
    "/opt/blender/blender",
    # Common PATH-visible names
    "blender",
]

# ── Conversion defaults ────────────────────────────────────────
DEFAULT_SPHERE_MODE = "NONE"
DEFAULT_AMBIENT = 0.0
DEFAULT_DOUBLE_SIDED = False
DEFAULT_APPLY_TRANSFORMS = True


# ================================================================
# Helpers
# ================================================================

def find_blender(hint=None):
    """Locate the Blender executable.  --blender > hint > PATH > candidates."""
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
    Return a list of (model_name, pmx_path, output_dir, output_glb) tuples.
    If subdir is given, only scan data/inputs/<subdir>/.
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
                   sphere_mode=DEFAULT_SPHERE_MODE,
                   ambient_strength=DEFAULT_AMBIENT,
                   force_double_sided=DEFAULT_DOUBLE_SIDED,
                   apply_transforms=DEFAULT_APPLY_TRANSFORMS):
    """Spawn Blender headless to convert one PMX → GLB."""
    cmd = [
        str(blender_path),
        "--background",
        "--python", str(CONVERT_SCRIPT),
        "--",
        "--input_pmx", str(pmx_path),
        "--output_glb", str(output_glb),
        "--sphere_mode", sphere_mode,
        "--ambient_strength", str(ambient_strength),
    ]

    if force_double_sided:
        cmd.append("--force_double_sided")
    if not apply_transforms:
        pass  # convert.py always applies transforms — extend if needed.

    print(f"  → blender {pmx_path.name} → {output_glb.name}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    # Print Blender's output (filtered)
    for line in result.stdout.splitlines():
        if any(tag in line for tag in ("[convert]", "Error", "ERROR", "Warning", "Saved")):
            print(f"    {line.strip()}")
    if result.stderr:
        for line in result.stderr.splitlines():
            if "Error" in line or "Warning" in line or "AL lib" not in line:
                print(f"    [stderr] {line.strip()}", file=sys.stderr)

    return result.returncode == 0


# ================================================================
# Commands
# ================================================================

def cmd_build(args):
    """Scan and convert all (or one) model(s)."""
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
            sphere_mode=args.sphere_mode,
            ambient_strength=args.ambient_strength,
            force_double_sided=args.force_double_sided,
        )
        if ok:
            success += 1
        else:
            failed += 1
            print(f"  ❌ FAILED: {pmx_path}")

    print()
    print(f"── Done: {success} converted, {failed} failed ──")
    return 0 if failed == 0 else 1


def cmd_watch(args):
    """Watch for new PMX models and convert them as they appear."""
    blender = find_blender(args.blender)
    if not blender:
        print("ERROR: Blender not found. Use --blender /path/to/blender to specify.")
        return 1

    print(f"Watching {INPUTS_DIR} for new models (poll every {args.interval}s) ...")
    print("Press Ctrl+C to stop.\n")

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
                    print(f"New model detected: {pmx_path}")
                    run_conversion(
                        blender, pmx_path, out_glb,
                        sphere_mode=args.sphere_mode,
                        ambient_strength=args.ambient_strength,
                        force_double_sided=args.force_double_sided,
                    )
                seen = current
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nWatch stopped.")
    return 0


# ================================================================
# CLI
# ================================================================

def main():
    parser = argparse.ArgumentParser(
        prog="bridge-build",
        description="MMD (PMX) → glTF auto-converter for Blender",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  uv run python main.py                          convert all models\n"
            "  uv run python main.py Melusine05_Mamere         convert one model\n"
            "  uv run python main.py -b /opt/blender/blender   custom blender path\n"
            "  uv run python main.py --watch                   watch for new models\n"
        ),
    )

    # Model name (optional positional)
    parser.add_argument(
        "model", nargs="?",
        help="Subdirectory name in data/inputs/ (omit to convert all models)",
    )

    # Global options
    parser.add_argument(
        "-b", "--blender",
        help="Path to Blender executable (auto-detected if omitted)",
    )
    parser.add_argument(
        "--sphere-mode", choices=["NONE", "AUTO", "ALL"],
        default=DEFAULT_SPHERE_MODE,
        help="Sphere map handling (default: NONE)",
    )
    parser.add_argument(
        "--ambient-strength", type=float, default=DEFAULT_AMBIENT,
        help="Ambient color strength 0.0-1.0 (default: 0.0)",
    )
    parser.add_argument(
        "--force-double-sided", action="store_true",
        default=DEFAULT_DOUBLE_SIDED,
        help="Force all materials double-sided",
    )
    parser.add_argument(
        "--watch", "-w", action="store_true",
        help="Watch mode: poll for new PMX files and convert automatically",
    )
    parser.add_argument(
        "--interval", "-i", type=int, default=10,
        help="Polling interval in seconds for watch mode (default: 10)",
    )

    args = parser.parse_args()

    if args.watch:
        return cmd_watch(args)
    return cmd_build(args)


if __name__ == "__main__":
    sys.exit(main())
