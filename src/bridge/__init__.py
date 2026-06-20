"""
Bridge — MMD (PMX) → glTF auto-converter.

A 3-layer pipeline:
  1. orchestrator — CLI entrypoint, scans data/inputs/, spawns Blender headless
  2. blender_driver — runs inside Blender, orchestrates import → convert → export
  3. addon        — Blender add-on registered to View3D sidebar (material conversion,
                   bone renaming, GLB export)
"""

__version__ = "0.2.0"

from pathlib import Path

# Absolute path to the project root (parent of src/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
