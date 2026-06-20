"""
MMD (PMX) → glTF conversion script for Blender.

Runs inside Blender's Python (headless). Called by bridge.cli.

Usage (via cli):
  blender --background --python src/bridge/blender_runner.py -- \\
    --input_pmx /path/to/model.pmx \\
    --output_glb /path/to/output.glb

Arguments after "--" are parsed by this script:
  --input_pmx       Path to the .pmx file to convert
  --output_glb      Path where the .glb file will be written
  --sphere_mode     NONE | AUTO | ALL  (default: NONE)
  --force_double_sided  (flag)
  --ambient_strength    float (default: 0.0)
"""

import bpy
import os
import sys
from pathlib import Path

# Project root derived from this file's location: src/bridge/blender_runner.py
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ============================================================
# Argument parsing (args after "--" in blender invocation)
# ============================================================

def parse_args(argv):
    """Parse --key value pairs from sys.argv (after the '--' marker)."""
    args = {
        "input_pmx": None,
        "output_glb": None,
        "sphere_mode": "NONE",
        "force_double_sided": False,
        "ambient_strength": 0.0,
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
        elif raw[i] == "--sphere_mode":
            args["sphere_mode"] = raw[i + 1]
            i += 2
        elif raw[i] == "--force_double_sided":
            args["force_double_sided"] = True
            i += 1
        elif raw[i] == "--ambient_strength":
            args["ambient_strength"] = float(raw[i + 1])
            i += 2
        else:
            i += 1

    return args


# ============================================================
# Add-on management
# ============================================================

def log(msg):
    print(f"[convert] {msg}")


def find_addon_path():
    """Locate the addon module at src/bridge/addon.py."""
    return str(_PROJECT_ROOT / "src" / "bridge" / "addon.py")


def install_and_enable_addon():
    """
    Register the MMD → glTF addon in Blender.

    Adds the project's src/ to sys.path and imports the bridge.addon
    module directly, rather than copying the addon file to Blender's
    addons directory (which would break the src/ layout).
    """
    addon_path = find_addon_path()
    if not addon_path or not os.path.isfile(addon_path):
        log(f"ERROR: addon not found at {addon_path} — cannot enable")
        return False

    # Ensure project src/ is on sys.path
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

    # Register the add-on classes
    try:
        if hasattr(mod, "register"):
            mod.register()
            log("Registered add-on: bridge.addon")
        return True
    except Exception as e:
        log(f"ERROR: Failed to register add-on '{module_name}': {e}")
        return False


# ============================================================
# Conversion steps
# ============================================================

def import_pmx(pmx_path):
    """Import the PMX model into the scene."""
    log(f"Importing {pmx_path} ...")

    # Clear default scene
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    bpy.ops.mmd_tools.import_model(
        filepath=pmx_path,
        types={"MESH", "ARMATURE", "PHYSICS", "DISPLAY", "MORPHS"},
        scale=1.0,
    )
    log("Import done.")


def convert_materials(sphere_mode="NONE", force_double_sided=False, ambient_strength=0.0):
    """Convert MMD materials to Principled BSDF."""
    log(f"Converting materials (sphere={sphere_mode}, double_sided={force_double_sided}, ambient={ambient_strength}) ...")
    bpy.ops.mmd.convert_materials(
        sphere_mode=sphere_mode,
        force_double_sided=force_double_sided,
        ambient_strength=ambient_strength,
    )
    log("Material conversion done.")


def rename_bones():
    """Rename bones for glTF compatibility."""
    log("Renaming bones ...")
    bpy.ops.mmd.rename_bones()
    log("Bone rename done.")


def export_glb(output_path, export_animations=True, export_morphs=True, apply_transforms=True):
    """Export as GLB."""
    log(f"Exporting to {output_path} ...")
    bpy.ops.mmd.export_gltf(
        filepath=output_path,
        export_animations=export_animations,
        export_morphs=export_morphs,
        apply_transforms=apply_transforms,
    )
    log(f"Export done: {output_path}")


# ============================================================
# Main
# ============================================================

def main():
    args = parse_args(sys.argv)

    input_pmx = args["input_pmx"]
    output_glb = args["output_glb"]

    if not input_pmx or not os.path.isfile(input_pmx):
        log(f"ERROR: --input_pmx is required and must exist: {input_pmx}")
        sys.exit(1)

    if not output_glb:
        log("ERROR: --output_glb is required")
        sys.exit(1)

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_glb), exist_ok=True)

    # Step 0: Install & enable the add-on
    if not install_and_enable_addon():
        sys.exit(1)

    # Step 1: Import PMX
    import_pmx(input_pmx)

    # Step 2: Convert materials
    convert_materials(
        sphere_mode=args["sphere_mode"],
        force_double_sided=args["force_double_sided"],
        ambient_strength=args["ambient_strength"],
    )

    # Step 3: Rename bones
    rename_bones()

    # Step 4: Export as GLB
    export_glb(output_glb)

    log("=== Conversion complete ===")


if __name__ == "__main__":
    main()
