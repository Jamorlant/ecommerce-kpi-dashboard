"""命令行入口：python -m ecommerce_kpi <generate|metrics|render|all>。

退出码约定：0 成功 / 1 程序缺陷 / 2 数据或配置不满足契约。
CI 依赖这个约定区分"环境没装好"与"代码写错了"。
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from ecommerce_kpi.config import load_settings
from ecommerce_kpi.errors import KpiError
from ecommerce_kpi.generate import generate_dataset, write_dataset
from ecommerce_kpi.logging_setup import configure_logging
from ecommerce_kpi.pipeline import run_metrics
from ecommerce_kpi.render import render_dashboard

logger = logging.getLogger(__name__)

COMMANDS = ("generate", "metrics", "render", "all")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ecommerce_kpi",
        description="合成电商数据 → 指标计算 → 单文件看板",
    )
    parser.add_argument("--env-file", type=Path, default=None, help="自定义 .env 路径（默认仓库根目录 .env）")
    parser.add_argument(
        "--log-level", default=None, choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="覆盖 KPI_LOG_LEVEL"
    )
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="<generate|metrics|render|all>")
    subparsers.add_parser("generate", help="重新生成 data/*.csv（固定种子，结果可复现）")
    subparsers.add_parser("metrics", help="计算指标，输出 data/metrics.json")
    subparsers.add_parser("render", help="内联数据与 ECharts，输出 dashboard/index.html")
    subparsers.add_parser("all", help="依次执行 generate → metrics → render")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        settings = load_settings(args.env_file)
        configure_logging(args.log_level or settings.log_level)

        if args.command in ("generate", "all"):
            started = time.perf_counter()
            frames = generate_dataset(settings)
            write_dataset(frames, settings.data_dir)
            logger.info("数据生成完成，用时 %.1fs", time.perf_counter() - started)

        if args.command in ("metrics", "all"):
            started = time.perf_counter()
            run_metrics(settings)
            logger.info("指标计算完成，用时 %.1fs", time.perf_counter() - started)

        if args.command in ("render", "all"):
            render_dashboard(settings)

        return 0
    except KpiError as exc:
        logging.getLogger(__name__).error("%s", exc)
        return 2
    except Exception:  # noqa: BLE001 - 顶层兜底，必须记录完整栈后返回非零
        logging.getLogger(__name__).exception("未预期错误，请提交 issue 并附上 traceback")
        return 1
