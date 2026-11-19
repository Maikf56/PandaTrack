"""pytest 全局配置：把 packages/*/src 注入 sys.path（src 布局，monorepo 直接跑）。"""
from __future__ import annotations

import sys
from pathlib import Path

import os

ROOT = Path(__file__).resolve().parents[1]
for pkg_src in sorted((ROOT / "packages").glob("*/src")):
    if str(pkg_src) not in sys.path:
        sys.path.insert(0, str(pkg_src))

# 真实页样本不在仓库内；服务器约定放 ~/.pandatrack-secrets/usps_sample.html。
# 未显式设 PT_USPS_SAMPLE 时自动发现，避免每次手工带环境变量。
if not os.environ.get("PT_USPS_SAMPLE"):
    auto = Path.home() / ".pandatrack-secrets" / "usps_sample.html"
    if auto.exists():
        os.environ["PT_USPS_SAMPLE"] = str(auto)
