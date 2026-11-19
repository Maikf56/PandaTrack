"""pytest 全局配置：把 packages/*/src 注入 sys.path（src 布局，monorepo 直接跑）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for pkg_src in sorted((ROOT / "packages").glob("*/src")):
    if str(pkg_src) not in sys.path:
        sys.path.insert(0, str(pkg_src))
