"""日志配置。

为什么需要分级：数据生成/指标计算/看板构建三个阶段耗时差异很大，
INFO 记录关键产物与行数，WARNING 记录异常检测的命中情况，
DEBUG 才打印分步细节，方便面试官"看一次完整运行"而不会被淹没。
"""

from __future__ import annotations

import logging
import sys

_FORMAT = "%(asctime)s %(levelname)-7s %(name)-22s | %(message)s"
_DATE_FORMAT = "%H:%M:%S"


def configure_logging(level: str = "INFO") -> None:
    """幂等地配置根 logger（重复调用不会叠加 handler）。"""
    root = logging.getLogger()
    root.setLevel(level)

    for handler in list(root.handlers):
        if getattr(handler, "_kpi_handler", False):
            root.removeHandler(handler)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT))
    handler._kpi_handler = True  # type: ignore[attr-defined]
    root.addHandler(handler)
