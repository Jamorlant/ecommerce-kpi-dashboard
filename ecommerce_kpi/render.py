"""看板构建：把数据与 ECharts 内联进单个 HTML。

为什么坚持单文件：读者不应为了看一张图去装服务、跑 npm；
代价是 1.3MB 的构建产物进入版本库，这个取舍写在 docs/architecture.md。
"""

from __future__ import annotations

import json
import logging

from ecommerce_kpi.config import Settings
from ecommerce_kpi.errors import DataContractError

logger = logging.getLogger(__name__)

DATA_PLACEHOLDER = "__DATA_JSON__"
ECHARTS_PLACEHOLDER = "__ECHARTS__"


def render_dashboard(settings: Settings) -> str:
    """返回生成的 HTML 文本，并写入 dashboard/index.html。"""
    template_path = settings.dashboard_dir / "template.html"
    echarts_path = settings.dashboard_dir / "vendor" / "echarts.min.js"
    metrics_path = settings.data_dir / "metrics.json"

    for path, hint in (
        (template_path, "看板模板缺失"),
        (echarts_path, "请将 ECharts 放入 dashboard/vendor/"),
        (metrics_path, "请先运行 python -m ecommerce_kpi metrics"),
    ):
        if not path.exists():
            raise DataContractError(f"{hint}：{path}")

    template = template_path.read_text(encoding="utf-8")
    for placeholder in (DATA_PLACEHOLDER, ECHARTS_PLACEHOLDER):
        if placeholder not in template:
            raise DataContractError(f"模板 {template_path.name} 缺少占位符 {placeholder}")

    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    html = template.replace(
        DATA_PLACEHOLDER,
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    ).replace(ECHARTS_PLACEHOLDER, echarts_path.read_text(encoding="utf-8"))

    out = settings.dashboard_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    logger.info("看板已生成：%s（%.2f MB，ECharts 已内联，可离线双击打开）", out.name, out.stat().st_size / 1024 / 1024)
    return str(out)
