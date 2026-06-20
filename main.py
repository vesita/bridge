#!/usr/bin/env -S uv run
"""
Bridge — MMD (PMX) → glTF auto-converter.

Entry point for the conversion pipeline. Delegates to bridge.cli.

Usage:
  uv run python main.py                          # Convert all models
  uv run python main.py Melusine05_Mamere         # Convert one model
  uv run python main.py --blender /path/to/blender  # Custom Blender path
  uv run python main.py --watch                   # Watch for new models
"""
import sys
from pathlib import Path

# Add src/ to the module search path so `from bridge import ...` works
_src = str(Path(__file__).parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from bridge.cli import main

sys.exit(main())
