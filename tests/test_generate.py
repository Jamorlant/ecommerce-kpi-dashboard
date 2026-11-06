"""数据生成测试：固定种子可复现是作品集可信度的前提。"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from ecommerce_kpi.generate import build_dim_date, build_fulfillment, build_sales, promo_intensity


def test_same_seed_reproduces_identical_sales() -> None:
    first = build_sales(date(2025, 6, 1), date(2025, 6, 3), np.random.default_rng(42))
    second = build_sales(date(2025, 6, 1), date(2025, 6, 3), np.random.default_rng(42))

    pd.testing.assert_frame_equal(first, second)


def test_different_seed_produces_different_data() -> None:
    first = build_sales(date(2025, 6, 1), date(2025, 6, 3), np.random.default_rng(42))
    second = build_sales(date(2025, 6, 1), date(2025, 6, 3), np.random.default_rng(7))

    assert first["gmv"].sum() != second["gmv"].sum()


def test_fulfillment_order_counts_match_sales() -> None:
    rng = np.random.default_rng(42)
    sales = build_sales(date(2025, 6, 1), date(2025, 6, 2), rng)
    fulfillment = build_fulfillment(sales, rng)

    assert fulfillment["orders"].sum() == sales["orders"].sum()


def test_promo_intensity_peaks_on_final_day() -> None:
    intense, label = promo_intensity(date(2025, 6, 18), "天猫")
    calm, calm_label = promo_intensity(date(2025, 3, 20), "天猫")

    assert label == "618"
    assert calm_label == ""
    assert intense == pytest.approx(2.0)
    assert calm == pytest.approx(1.0)


def test_dim_date_marks_promo_days() -> None:
    dim = build_dim_date(date(2025, 6, 17), date(2025, 6, 19))

    assert dim["is_promo"].sum() == 2  # 6/18 与 6/19 落在 618 窗口内
    assert set(dim.loc[dim["is_promo"] == 1, "promo_name"]) == {"618"}
