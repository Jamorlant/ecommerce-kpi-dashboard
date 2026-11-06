"""流水线契约测试：保证看板依赖的 JSON 结构不被无意破坏。"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from ecommerce_kpi.errors import DataContractError
from ecommerce_kpi.pipeline import build_payload


def test_payload_contains_all_dashboard_blocks(mini_dataset) -> None:
    sales, fulfillment, dim = mini_dataset
    payload = build_payload(sales, fulfillment, dim)

    assert len(payload["kpis"]) == 6
    assert payload["meta"]["months"][-1] == "2025-02"
    assert len(payload["meta"]["months"]) == 14
    assert len(payload["monthly_platform"]) == 14 * 4
    assert payload["monthly_platform"][0]["sla48_rate"] > 0
    assert payload["anomalies"] == []
    assert len(payload["insights"]) == 4  # 无异常时不出"异常定位"这条
    assert len(payload["sla_promo"]) == 2
    json.dumps(payload, ensure_ascii=False, default=float)


def test_promo_windows_merge_consecutive_days(mini_dataset) -> None:
    sales, fulfillment, dim = mini_dataset
    payload = build_payload(sales, fulfillment, dim)

    # 测试集只覆盖到 2025-02，因此仅 2024-06 落在大促窗口内
    assert payload["meta"]["promo_windows"] == [{"name": "618", "start": "2024-06-01", "end": "2024-06-01"}]


def test_short_period_raises_instead_of_faking_yoy(mini_dataset) -> None:
    sales, fulfillment, dim = mini_dataset
    cutoff = pd.Timestamp("2024-03-01")
    with pytest.raises(DataContractError, match="无法计算同比"):
        build_payload(
            sales[sales["date"] < cutoff],
            fulfillment[fulfillment["date"] < cutoff],
            dim[dim["date"] < cutoff],
        )
