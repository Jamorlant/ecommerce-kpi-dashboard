"""指标口径的唯一实现（纯计算，不读写文件）。

每个指标都在这里定义分子与分母，README 的"指标口径"表、Power BI 的 DAX、
FineBI 的计算字段都以本模块为准；三处不一致就是口径事故，所以不做第二套实现。
"""

from __future__ import annotations

import pandas as pd

# 分桶中值用于加权平均（小时）：区间中位数，避免用边界造成系统偏差
SLA_MIDPOINT: dict[str, int] = {"0-12h": 6, "12-24h": 18, "24-48h": 36, "48-72h": 60, "72h+": 96}
FAST_BUCKETS: frozenset[str] = frozenset({"0-12h", "12-24h", "24-48h"})


def pct_change(current: float, previous: float | None) -> float | None:
    """环比/同比：分母为 0 或缺失时返回 None（看板显示"—"，而不是伪造 0%）。"""
    if previous is None or previous == 0:
        return None
    return (float(current) - float(previous)) / float(previous)


def aggregate(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """按维度汇总并派生比率型指标。

    比率一律"先汇总分子分母、后相除"，而不是对每日比率取平均：
    否则小体量日期会被过度加权（Simpson 悖论）。
    """
    out = df.groupby(keys, as_index=False).agg(
        gmv=("gmv", "sum"),
        orders=("orders", "sum"),
        visitors=("visitors", "sum"),
        refund_orders=("refund_orders", "sum"),
        refund_amount=("refund_amount", "sum"),
    )
    out["aov"] = out["gmv"] / out["orders"]
    out["cvr"] = out["orders"] / out["visitors"]
    out["refund_rate"] = out["refund_orders"] / out["orders"]
    return out


def sla_metrics(fulfillment: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """履约指标：48h 达成率与加权平均时长。

    48h 达成率的分母是"有履约记录的分桶订单总数"，与销售订单数在数据层保证相等。
    """
    frame = fulfillment.copy()
    frame["fast48_orders"] = frame["orders"] * frame["sla_bucket"].isin(FAST_BUCKETS).astype(int)
    frame["hours"] = frame["sla_bucket"].map(SLA_MIDPOINT)
    frame["hours_weighted"] = frame["orders"] * frame["hours"]

    out = frame.groupby(keys, as_index=False).agg(
        sla_orders=("orders", "sum"),
        fast48_orders=("fast48_orders", "sum"),
        hours_weighted=("hours_weighted", "sum"),
    )
    out["sla48_rate"] = out["fast48_orders"] / out["sla_orders"]
    out["avg_hours"] = out["hours_weighted"] / out["sla_orders"]
    return out


def add_month_column(frame: pd.DataFrame) -> pd.DataFrame:
    """统一月份口径为 YYYY-MM 字符串，便于和看板 JSON 的 month 字段直接对齐。"""
    out = frame.copy()
    out["month"] = out["date"].dt.strftime("%Y-%m")
    return out


def records(frame: pd.DataFrame, columns: list[str]) -> list[dict]:
    """转成 JSON 友好结构；保留 6 位小数以隐藏浮点尾差，同时不损失业务精度。"""
    return frame[columns].round(6).to_dict(orient="records")
