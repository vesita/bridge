"""
允许 `python -m bridge` 运行编排器 CLI。
"""
import sys

from bridge.cli import main

sys.exit(main())
