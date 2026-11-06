"""输入数据契约校验。

为什么显式校验：数据文件可能被外部替换（换周期、换导出源），
没有校验的话错误会以 KeyError / 除零的形式散落在下游，难以定位。
这里只在边界（读文件之后）做一次检查。
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from ecommerce_kpi.errors import DataContractError


def validate_frame(
    name: str,
    frame: pd.DataFrame,
    *,
    columns: Sequence[str],
    numeric: Sequence[str] = (),
    date_columns: Sequence[str] = (),
) -> None:
    if frame.empty:
        raise DataContractError(f"{name} 没有数据行")
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise DataContractError(f"{name} 缺少列 {missing}（期望 {list(columns)}）")
    for column in numeric:
        if not pd.api.types.is_numeric_dtype(frame[column]):
            raise DataContractError(f"{name}.{column} 必须是数值型，实际为 {frame[column].dtype}")
    for column in date_columns:
        if not pd.api.types.is_datetime64_any_dtype(frame[column]):
            raise DataContractError(f"{name}.{column} 必须是日期型，实际为 {frame[column].dtype}")


def order_consistency_gap(sales: pd.DataFrame, fulfillment: pd.DataFrame) -> float:
    """履约分桶订单数与销售订单数的相对偏差（0 表示完全一致）。

    两者来自不同事实表，粒度不同；偏差过大说明数据被手工改过，
    应作为告警而不是静默通过。
    """
    sales_total = float(sales["orders"].sum())
    fulfillment_total = float(fulfillment["orders"].sum())
    if sales_total <= 0:
        raise DataContractError("销售订单总数为 0，无法计算偏差")
    return abs(fulfillment_total - sales_total) / sales_total
