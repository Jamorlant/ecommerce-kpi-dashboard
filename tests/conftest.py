"""测试共用的小型数据集：只保留能驱动分支的最少维度。"""

from __future__ import annotations

import pandas as pd
import pytest

PLATFORMS = ("天猫", "京东", "抖音", "拼多多")
CATEGORIES = ("美妆个护", "数码3C")
CHANNELS = ("自然搜索", "直播")
REFUND_RATE = {"天猫": 0.10, "京东": 0.06, "抖音": 0.20, "拼多多": 0.12}


@pytest.fixture
def mini_dataset() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """14 个完整月 × 4 平台 × 2 品类 × 2 渠道，足以跑通同比与全部结论分支。"""
    months = pd.date_range("2024-01-01", periods=14, freq="MS")

    sales_rows: list[dict] = []
    fulfill_rows: list[dict] = []
    for month_index, month_start in enumerate(months):
        for platform_index, platform in enumerate(PLATFORMS):
            for category_index, category in enumerate(CATEGORIES):
                for channel_index, channel in enumerate(CHANNELS):
                    orders = 100 + 10 * month_index + 5 * platform_index + 3 * category_index + channel_index
                    price = 100 + 20 * platform_index
                    refunds = int(orders * REFUND_RATE[platform])
                    sales_rows.append(
                        {
                            "date": month_start,
                            "platform": platform,
                            "category": category,
                            "channel": channel,
                            "orders": orders,
                            "gmv": round(orders * price, 2),
                            "visitors": orders * 20,
                            "refund_orders": refunds,
                            "refund_amount": round(refunds * price, 2),
                        }
                    )
                    fast = int(orders * 0.9)
                    for bucket, count in (("0-12h", fast), ("72h+", orders - fast)):
                        if count:
                            fulfill_rows.append(
                                {
                                    "date": month_start,
                                    "platform": platform,
                                    "category": category,
                                    "sla_bucket": bucket,
                                    "orders": count,
                                }
                            )

    dim_rows = [
        {
            "date": month_start,
            "year": month_start.year,
            "quarter": f"{month_start.year}Q{((month_start.month - 1) // 3) + 1}",
            "month_no": month_start.month,
            "month_name": f"{month_start.month}月",
            "iso_week": f"{month_start.isocalendar().year}-W{month_start.isocalendar().week:02d}",
            "weekday_no": month_start.weekday() + 1,
            "weekday_name": "周一",
            "is_weekend": int(month_start.weekday() >= 5),
            "is_promo": int(month_start.month == 6),
            "promo_name": "618" if month_start.month == 6 else "",
        }
        for month_start in months
    ]

    return pd.DataFrame(sales_rows), pd.DataFrame(fulfill_rows), pd.DataFrame(dim_rows)
