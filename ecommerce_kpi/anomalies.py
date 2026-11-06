"""退款率异常检测：把"看起来高"变成"可解释的偏离"。

为什么不用固定阈值：大促会让所有品类普涨，绝对阈值会满屏误报；
为什么用前 3 个月中位数：中位数对单月尖峰不敏感，比均值更稳。
双阈值（绝对 ≥2.5pp 且 相对 ≥18%）是这两个问题的折中，参数集中在文件顶部便于评审。
"""

from __future__ import annotations

import pandas as pd

ABSOLUTE_THRESHOLD_PP = 0.025
RELATIVE_THRESHOLD = 1.18
LOOKBACK_MONTHS = 3
HIGH_SEVERITY_PP = 0.05


def detect_anomalies(
    monthly_platform_category: pd.DataFrame,
    *,
    absolute_threshold: float = ABSOLUTE_THRESHOLD_PP,
    relative_threshold: float = RELATIVE_THRESHOLD,
    lookback: int = LOOKBACK_MONTHS,
    top_n: int = 6,
) -> list[dict]:
    """返回按偏离幅度降序的异常列表；无异常时返回空列表（不是 None）。"""
    anomalies: list[dict] = []
    for (platform, category), group in monthly_platform_category.groupby(["platform", "category"]):
        series = group.sort_values("month").reset_index(drop=True)
        for index in range(lookback - 1, len(series)):
            window = series.loc[max(0, index - lookback) : index - 1, "refund_rate"]
            baseline = float(window.median())
            rate = float(series.loc[index, "refund_rate"])
            excess = rate - baseline
            if excess < absolute_threshold or rate < baseline * relative_threshold:
                continue
            row = series.loc[index]
            anomalies.append(
                {
                    "platform": platform,
                    "category": category,
                    "month": row["month"],
                    "refund_rate": rate,
                    "baseline": baseline,
                    "excess_pp": excess * 100,
                    "orders": int(row["orders"]),
                    "refund_orders": int(row["refund_orders"]),
                    "severity": "high" if excess >= HIGH_SEVERITY_PP else "medium",
                }
            )
    anomalies.sort(key=lambda item: item["excess_pp"], reverse=True)
    return anomalies[:top_n]
