"""异常检测测试：验证双阈值不会漏报尖峰、也不会把普涨当异常。"""

from __future__ import annotations

import pandas as pd
import pytest

from ecommerce_kpi.anomalies import detect_anomalies


def _series(rates: list[float], platform: str = "抖音", category: str = "美妆个护") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "month": [f"2025-{index + 1:02d}" for index in range(len(rates))],
            "platform": platform,
            "category": category,
            "orders": [1000] * len(rates),
            "refund_orders": [int(rate * 1000) for rate in rates],
            "refund_rate": rates,
        }
    )


def test_detects_spike_above_both_thresholds() -> None:
    frame = _series([0.10, 0.10, 0.11, 0.25])
    result = detect_anomalies(frame)

    assert len(result) == 1
    assert result[0]["month"] == "2025-04"
    assert result[0]["baseline"] == pytest.approx(0.10)
    assert result[0]["excess_pp"] == pytest.approx(15.0, abs=0.15)
    assert result[0]["severity"] == "high"


def test_ignores_flat_series() -> None:
    assert detect_anomalies(_series([0.10, 0.10, 0.10, 0.10])) == []


def test_ignores_relative_rise_below_absolute_threshold() -> None:
    # 0.01 → 0.03：相对 +200%，但只抬升 2pp，不足以判定异常
    assert detect_anomalies(_series([0.01, 0.01, 0.01, 0.03])) == []


def test_ignores_absolute_rise_below_relative_threshold() -> None:
    # 0.40 → 0.43：绝对 +3pp，但相对仅 +7.5%，属于正常波动
    assert detect_anomalies(_series([0.40, 0.40, 0.40, 0.43])) == []


def test_sorts_by_excess_and_truncates() -> None:
    frame = pd.concat(
        [
            _series([0.10, 0.10, 0.10, 0.15]),
            _series([0.10, 0.10, 0.10, 0.30], category="服饰鞋包"),
        ],
        ignore_index=True,
    )
    result = detect_anomalies(frame, top_n=1)

    assert len(result) == 1
    assert result[0]["category"] == "服饰鞋包"
