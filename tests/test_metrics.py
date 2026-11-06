"""指标口径的单元测试：这里错了，README 与 BI 复刻文档全错。"""

from __future__ import annotations

import pandas as pd
import pytest

from ecommerce_kpi.metrics import aggregate, pct_change, sla_metrics


def test_pct_change_returns_none_when_baseline_missing_or_zero() -> None:
    assert pct_change(120, 100) == pytest.approx(0.2)
    assert pct_change(100, 0) is None
    assert pct_change(100, None) is None


def test_aggregate_derives_ratios_from_sums_not_averages() -> None:
    frame = pd.DataFrame(
        {
            "platform": ["天猫", "天猫"],
            "orders": [10, 90],
            "gmv": [1000.0, 9000.0],
            "visitors": [100, 1000],
            "refund_orders": [1, 9],
            "refund_amount": [100.0, 900.0],
        }
    )
    result = aggregate(frame, ["platform"]).iloc[0]

    assert result["orders"] == 100
    assert result["gmv"] == 10000.0
    assert result["aov"] == pytest.approx(100.0)
    assert result["cvr"] == pytest.approx(100 / 1100)
    assert result["refund_rate"] == pytest.approx(0.1)


def test_sla_metrics_weights_bucket_midpoints() -> None:
    frame = pd.DataFrame(
        {
            "platform": ["京东"] * 5,
            "sla_bucket": ["0-12h", "12-24h", "24-48h", "48-72h", "72h+"],
            "orders": [50, 30, 10, 8, 2],
        }
    )
    result = sla_metrics(frame, ["platform"]).iloc[0]

    assert result["sla_orders"] == 100
    assert result["fast48_orders"] == 90
    assert result["sla48_rate"] == pytest.approx(0.90)
    # 50*6 + 30*18 + 10*36 + 8*60 + 2*96 = 1872 → 18.72 小时
    assert result["avg_hours"] == pytest.approx(18.72)
