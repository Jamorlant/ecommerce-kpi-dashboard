"""
生成合成电商多平台经营数据（完全虚构，不含任何真实企业或个人信息）。

口径与结构：
- fact_sales.csv        日期 × 平台 × 品类 × 渠道  的每日销售明细
- fact_fulfillment.csv  日期 × 平台 × 品类          的履约时效分桶（订单数）
                         同一日期/平台/品类的各分桶订单数之和 = fact_sales 中对应订单数之和
- dim_date.csv          日历维度表，含星期、促销窗口标记

运行：python scripts/generate_data.py
输出：data/*.csv
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20260101
START = date(2024, 1, 1)
END = date(2025, 8, 31)

OUT_DIR = Path(__file__).resolve().parents[1] / "data"

PLATFORMS = ["天猫", "京东", "抖音", "拼多多"]
CATEGORIES = ["美妆个护", "数码3C", "服饰鞋包", "食品生鲜", "家居日用", "母婴玩具"]
CHANNELS = ["自然搜索", "付费推广", "直播", "内容种草", "私域"]

# 日均订单基数（用来刻画平台体量差异）
BASE_ORDERS = {"天猫": 1750, "京东": 1500, "抖音": 2100, "拼多多": 3100}

# 平台 × 品类 订单结构
CATEGORY_MIX = {
    "天猫": [0.24, 0.16, 0.26, 0.12, 0.14, 0.08],
    "京东": [0.14, 0.30, 0.12, 0.16, 0.18, 0.10],
    "抖音": [0.30, 0.08, 0.30, 0.18, 0.09, 0.05],
    "拼多多": [0.12, 0.10, 0.16, 0.30, 0.24, 0.08],
}

# 平台 × 渠道 访客结构
CHANNEL_MIX = {
    "天猫": [0.38, 0.27, 0.15, 0.12, 0.08],
    "京东": [0.45, 0.30, 0.08, 0.07, 0.10],
    "抖音": [0.12, 0.10, 0.55, 0.20, 0.03],
    "拼多多": [0.55, 0.28, 0.06, 0.04, 0.07],
}

# 客单价基准（元），再叠加品类系数
BASE_AOV = {"天猫": 210, "京东": 292, "抖音": 148, "拼多多": 68}
CATEGORY_AOV = {
    "美妆个护": 1.10,
    "数码3C": 2.65,
    "服饰鞋包": 1.00,
    "食品生鲜": 0.55,
    "家居日用": 1.05,
    "母婴玩具": 1.30,
}

# 支付转化率基准（支付订单数 / 访客数）
BASE_CVR = {"天猫": 0.032, "京东": 0.036, "抖音": 0.021, "拼多多": 0.045}
CHANNEL_CVR = {"自然搜索": 1.15, "付费推广": 0.90, "直播": 1.35, "内容种草": 0.75, "私域": 1.90}

# 退款率基准（退款订单数 / 支付订单数）
BASE_REFUND = {"天猫": 0.095, "京东": 0.062, "抖音": 0.200, "拼多多": 0.120}
CATEGORY_REFUND = {
    "美妆个护": 1.15,
    "数码3C": 0.55,
    "服饰鞋包": 1.45,
    "食品生鲜": 0.70,
    "家居日用": 0.85,
    "母婴玩具": 0.75,
}
CHANNEL_REFUND = {"自然搜索": 1.00, "付费推广": 0.95, "直播": 1.25, "内容种草": 1.10, "私域": 0.85}

# 星期波动（周一…周日）
WEEKDAY_FACTOR = {
    "天猫": [0.94, 0.88, 0.90, 0.96, 1.02, 1.13, 1.06],
    "京东": [0.97, 0.93, 0.94, 0.98, 1.01, 1.08, 1.04],
    "抖音": [0.92, 0.90, 0.94, 1.00, 1.05, 1.16, 1.10],
    "拼多多": [0.98, 0.96, 0.97, 1.00, 1.01, 1.05, 1.02],
}

# 履约时效分布：0-12h / 12-24h / 24-48h / 48-72h / 72h+
SLA_PROFILE = {
    "天猫": [0.28, 0.42, 0.24, 0.05, 0.01],
    "京东": [0.55, 0.34, 0.09, 0.015, 0.005],
    "抖音": [0.18, 0.36, 0.32, 0.10, 0.04],
    "拼多多": [0.20, 0.34, 0.31, 0.11, 0.04],
}
SLA_BUCKETS = ["0-12h", "12-24h", "24-48h", "48-72h", "72h+"]

# 促销窗口：(名称, 开始日, 结束日, 峰值订单倍数)
PROMOS = [
    ("618", date(2024, 5, 26), date(2024, 6, 18), 2.00),
    ("88会员节", date(2024, 8, 8), date(2024, 8, 11), 1.70),
    ("双11", date(2024, 10, 24), date(2024, 11, 11), 3.35),
    ("双12", date(2024, 12, 9), date(2024, 12, 12), 1.75),
    ("年货节", date(2025, 1, 6), date(2025, 1, 20), 1.95),
    ("38节", date(2025, 3, 5), date(2025, 3, 8), 1.60),
    ("618", date(2025, 5, 26), date(2025, 6, 18), 2.00),
    ("88会员节", date(2025, 8, 8), date(2025, 8, 11), 1.70),
]
PROMO_STRENGTH = {"天猫": 1.00, "京东": 0.95, "抖音": 1.35, "拼多多": 0.80}

# 全年增速（线性趋势，抖音最快）
YEAR_GROWTH = {"天猫": 0.06, "京东": 0.10, "抖音": 0.48, "拼多多": 0.20}


def daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def promo_intensity(d: date, platform: str) -> tuple[float, str]:
    """返回当日促销强度系数（1.0 = 平销）与促销名称。"""
    label = ""
    base = 1.0
    for name, s, e, peak in PROMOS:
        if not (s <= d <= e):
            continue
        label = name
        span = (e - s).days + 1
        progress = (d - s).days + 1
        # 促销曲线：前期预热爬坡，尾段冲刺，最后两天峰值
        ramp = 0.45 + 0.55 * math.sin(math.pi * min(progress / span, 1.0))
        if progress >= span - 1:
            ramp = 1.0
        effective_peak = 1.0 + (peak - 1.0) * PROMO_STRENGTH[platform]
        base = max(base, 1.0 + (effective_peak - 1.0) * ramp)
    return base, label


# 人为注入的退货异常窗口：(平台, 品类, 起始, 结束, 额外退款率)
REFUND_EVENTS = [
    ("抖音", "美妆个护", date(2025, 3, 1), date(2025, 3, 31), 0.090),
    ("抖音", "服饰鞋包", date(2024, 11, 8), date(2024, 11, 30), 0.060),
    ("拼多多", "家居日用", date(2025, 6, 1), date(2025, 6, 30), 0.035),
]


def build_sales(rng: np.random.Generator) -> pd.DataFrame:
    dates = list(daterange(START, END))
    total_days = len(dates)
    rows = []

    for platform in PLATFORMS:
        mix = CATEGORY_MIX[platform]
        ch_mix = CHANNEL_MIX[platform]
        for d in dates:
            t = (d - START).days / total_days
            trend = 1.0 + YEAR_GROWTH[platform] * t
            p_int, _ = promo_intensity(d, platform)
            wd = WEEKDAY_FACTOR[platform][d.weekday()]
            day_noise = rng.normal(0, 0.06)
            for ci, category in enumerate(CATEGORIES):
                cat_noise = rng.normal(0, 0.05)
                base_orders = BASE_ORDERS[platform] * mix[ci] * trend * p_int * wd
                base_orders *= math.exp(day_noise + cat_noise)
                # 品类自身的季节波动（服饰/美妆在换季月份略高）
                seasonal = 1.0 + 0.06 * math.sin(2 * math.pi * (d.timetuple().tm_yday / 365.0) + ci)
                base_orders *= seasonal
                total_cat_orders = max(0, int(round(base_orders)))

                for ch_i, channel in enumerate(CHANNELS):
                    share = ch_mix[ch_i] * rng.normal(1.0, 0.04)
                    orders = int(round(total_cat_orders * share))
                    if orders <= 0:
                        continue

                    aov = BASE_AOV[platform] * CATEGORY_AOV[category] * math.exp(rng.normal(0, 0.08))
                    # 直播渠道客单价波动更大
                    if channel == "直播":
                        aov *= math.exp(rng.normal(0, 0.10))
                    gmv = round(orders * aov, 2)

                    cvr = BASE_CVR[platform] * CHANNEL_CVR[channel] * math.exp(rng.normal(0, 0.08))
                    # 大促期间流量放大但转化被稀释
                    cvr /= 1.0 + 0.35 * max(0.0, p_int - 1.0)
                    visitors = int(round(orders / max(cvr, 1e-4)))

                    refund_rate = BASE_REFUND[platform] * CATEGORY_REFUND[category] * CHANNEL_REFUND[channel]
                    refund_rate *= 1.0 + 0.12 * max(0.0, p_int - 1.0)  # 大促冲动购买，退货更高
                    for ep, ec, es, ee, extra in REFUND_EVENTS:
                        if ep == platform and ec == category and es <= d <= ee:
                            refund_rate += extra
                    refund_rate = float(np.clip(refund_rate * math.exp(rng.normal(0, 0.07)), 0.005, 0.62))

                    refund_orders = int(round(orders * refund_rate))
                    refund_amount = round(refund_orders * aov * 0.92, 2)

                    rows.append(
                        (
                            d.isoformat(),
                            platform,
                            category,
                            channel,
                            orders,
                            gmv,
                            visitors,
                            refund_orders,
                            refund_amount,
                        )
                    )
    return pd.DataFrame(
        rows,
        columns=[
            "date",
            "platform",
            "category",
            "channel",
            "orders",
            "gmv",
            "visitors",
            "refund_orders",
            "refund_amount",
        ],
    )


def build_fulfillment(sales: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """把每个 日期×平台×品类 的订单数分配到时效分桶。"""
    grouped = sales.groupby(["date", "platform", "category"], as_index=False)["orders"].sum()
    rows = []
    # 促销日期的履约压力（按日期×平台）
    date_platform = grouped.groupby(["date", "platform"], as_index=False)["orders"].sum()
    pressure = {}
    for r in date_platform.itertuples():
        d = date.fromisoformat(r.date)
        p_int, _ = promo_intensity(d, r.platform)
        pressure[(r.date, r.platform)] = min(0.42, 0.14 * max(0.0, p_int - 1.0))

    for r in grouped.itertuples():
        base = np.array(SLA_PROFILE[r.platform], dtype=float)
        delay = pressure[(r.date, r.platform)]
        # 促销压力把前两档订单向 24h 之后迁移
        base = base.copy()
        base[2] += delay * (base[0] * 0.45 + base[1] * 0.35)
        base[3] += delay * (base[1] * 0.15)
        base[4] += delay * (base[0] * 0.05)
        base[0] *= 1 - 0.45 * delay
        base[1] *= 1 - 0.30 * delay
        base += rng.normal(0, 0.008, 5).clip(min=0)
        base = np.clip(base, 1e-6, None)
        base = base / base.sum()
        counts = rng.multinomial(int(r.orders), base)
        for bucket, n in zip(SLA_BUCKETS, counts):
            if n > 0:
                rows.append((r.date, r.platform, r.category, bucket, int(n)))
    return pd.DataFrame(rows, columns=["date", "platform", "category", "sla_bucket", "orders"])


def build_dim_date() -> pd.DataFrame:
    rows = []
    for d in daterange(START, END):
        label = ""
        for name, s, e, _peak in PROMOS:
            if s <= d <= e:
                label = name
                break
        iso = d.isocalendar()
        rows.append(
            (
                d.isoformat(),
                d.year,
                f"{d.year}Q{((d.month - 1) // 3) + 1}",
                d.month,
                f"{d.month}月",
                f"{iso.year}-W{iso.week:02d}",
                d.weekday() + 1,
                ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][d.weekday()],
                int(d.weekday() >= 5),
                int(bool(label)),
                label,
            )
        )
    return pd.DataFrame(
        rows,
        columns=[
            "date",
            "year",
            "quarter",
            "month_no",
            "month_name",
            "iso_week",
            "weekday_no",
            "weekday_name",
            "is_weekend",
            "is_promo",
            "promo_name",
        ],
    )


def main() -> None:
    rng = np.random.default_rng(SEED)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    sales = build_sales(rng)
    fulfillment = build_fulfillment(sales, rng)
    dim_date = build_dim_date()

    sales.to_csv(OUT_DIR / "fact_sales.csv", index=False, encoding="utf-8")
    fulfillment.to_csv(OUT_DIR / "fact_fulfillment.csv", index=False, encoding="utf-8")
    dim_date.to_csv(OUT_DIR / "dim_date.csv", index=False, encoding="utf-8")

    print(f"fact_sales        {len(sales):>7,} 行   GMV 合计 {sales.gmv.sum() / 1e8:.2f} 亿元")
    print(f"fact_fulfillment  {len(fulfillment):>7,} 行   订单 {fulfillment.orders.sum():,}")
    print(f"dim_date          {len(dim_date):>7,} 行")


if __name__ == "__main__":
    main()
