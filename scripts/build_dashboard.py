"""
将指标数据与 ECharts 库内联，生成可离线双击打开的单文件看板。

运行：python scripts/build_dashboard.py
输出：dashboard/index.html
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "dashboard" / "template.html"
ECHARTS = ROOT / "dashboard" / "vendor" / "echarts.min.js"
METRICS = ROOT / "data" / "metrics.json"
OUT = ROOT / "dashboard" / "index.html"


def main() -> None:
    template = TEMPLATE.read_text(encoding="utf-8")
    payload = json.loads(METRICS.read_text(encoding="utf-8"))
    echarts_js = ECHARTS.read_text(encoding="utf-8")

    html = template.replace(
        "__DATA_JSON__",
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    ).replace("__ECHARTS__", echarts_js)

    OUT.write_text(html, encoding="utf-8")
    size_mb = OUT.stat().st_size / 1024 / 1024
    print(f"生成 {OUT.relative_to(ROOT)}  单文件 {size_mb:.2f} MB（ECharts 已内联，无需联网）")


if __name__ == "__main__":
    main()
