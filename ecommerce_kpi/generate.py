"""合成数据生成：把 scenario.py 的建模假设展开为明细表。

为什么拆成三张表：销售事实与履约时效的粒度不同（渠道 vs 时效分桶），
合并成一张宽表会让订单数被重复计算，星型模型也无法干净聚合。
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ecommerce_kpi.config import Settings
from ecommerce_kpi.scenario import (
    BASE_AOV,
    BASE_CVR,
    BASE_ORDERS,
    BASE_REFUND,
    CATEGORIES,
    CATEGORY_AOV,
    CATEGORY_MIX,
    CATEGORY_REFUND,
    CHANNEL_CVR,
    CHANNEL_MIX,
    CHANNEL_REFUND,
    CHANNELS,
    DIM_DATE_COLUMNS,
    FULFILLMENT_COLUMNS,
    PLATFORMS,
    PROMO_STRENGTH,
    PROMOS,
    REFUND_EVENTS,
    SALES_COLUMNS,
    SLA_BUCKETS,
    SLA_PROFILE,
    WEEKDAY_FACTOR,
    YEAR_GROWTH,
)

logger = logging.getLogger(__name__)

WEEKDAY_NAMES: tuple[str, ...] = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def daterange(start: date, end: date) -> Iterator[date]:
    """含首尾的逐日迭代。"""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def promo_intensity(day: date, platform: str) -> tuple[float, str]:
    """返回当日促销强度（1.0 = 平销）与促销名称。

    曲线设计为预热爬坡、尾段冲刺、最后两天峰值，贴合真实大促的订单形态；
    平台差异用 PROMO_STRENGTH 表达（抖音对大促更敏感）。
    """
    label = ""
    base = 1.0
    for name, start, end, peak in PROMOS:
        if not (start <= day <= end):
            continue
        label = name
        span = (end - start).days + 1
        progress = (day - start).days + 1
        ramp = 0.45 + 0.55 * math.sin(math.pi * min(progress / span, 1.0))
        if progress >= span - 1:
            ramp = 1.0
        effective_peak = 1.0 + (peak - 1.0) * PROMO_STRENGTH[platform]
        base = max(base, 1.0 + (effective_peak - 1.0) * ramp)
    return base, label


def build_sales(start: date, end: date, rng: np.random.Generator) -> pd.DataFrame:
    """日期 × 平台 × 品类 × 渠道 的销售明细。"""
    total_days = (end - start).days + 1
    records: list[tuple[object, ...]] = []

    for platform in PLATFORMS:
        category_mix = CATEGORY_MIX[platform]
        channel_mix = CHANNEL_MIX[platform]
        for day in daterange(start, end):
            trend = 1.0 + YEAR_GROWTH[platform] * ((day - start).days / total_days)
            intensity, _ = promo_intensity(day, platform)
            weekday_factor = WEEKDAY_FACTOR[platform][day.weekday()]
            day_noise = rng.normal(0, 0.06)
            for index, category in enumerate(CATEGORIES):
                records.extend(
                    _category_day_rows(
                        platform=platform,
                        category=category,
                        category_index=index,
                        day=day,
                        category_mix_value=category_mix[index],
                        channel_mix=channel_mix,
                        trend=trend,
                        intensity=intensity,
                        weekday_factor=weekday_factor,
                        day_noise=day_noise,
                        rng=rng,
                    )
                )

    return pd.DataFrame(records, columns=list(SALES_COLUMNS))


def _category_day_rows(
    *,
    platform: str,
    category: str,
    category_index: int,
    day: date,
    category_mix_value: float,
    channel_mix: tuple[float, ...],
    trend: float,
    intensity: float,
    weekday_factor: float,
    day_noise: float,
    rng: np.random.Generator,
) -> list[tuple[object, ...]]:
    """单个 平台 × 品类 × 日 在 5 个渠道上的订单拆分。"""
    category_noise = rng.normal(0, 0.05)
    orders = BASE_ORDERS[platform] * category_mix_value * trend * intensity * weekday_factor
    orders *= math.exp(day_noise + category_noise)
    # 品类季节波动：换季月份服饰/美妆略高
    seasonal = 1.0 + 0.06 * math.sin(2 * math.pi * (day.timetuple().tm_yday / 365.0) + category_index)
    orders *= seasonal
    total_orders = max(0, int(round(orders)))

    rows: list[tuple[object, ...]] = []
    for index, channel in enumerate(CHANNELS):
        share = channel_mix[index] * rng.normal(1.0, 0.04)
        channel_orders = int(round(total_orders * share))
        if channel_orders <= 0:
            continue

        aov = BASE_AOV[platform] * CATEGORY_AOV[category] * math.exp(rng.normal(0, 0.08))
        if channel == "直播":
            aov *= math.exp(rng.normal(0, 0.10))  # 直播间客单价波动更大
        gmv = round(channel_orders * aov, 2)

        cvr = BASE_CVR[platform] * CHANNEL_CVR[channel] * math.exp(rng.normal(0, 0.08))
        cvr /= 1.0 + 0.35 * max(0.0, intensity - 1.0)  # 大促流量放大但转化被稀释
        visitors = int(round(channel_orders / max(cvr, 1e-4)))

        refund_rate = BASE_REFUND[platform] * CATEGORY_REFUND[category] * CHANNEL_REFUND[channel]
        refund_rate *= 1.0 + 0.12 * max(0.0, intensity - 1.0)  # 冲动购买抬高退货
        for event_platform, event_category, event_start, event_end, extra in REFUND_EVENTS:
            if event_platform == platform and event_category == category and event_start <= day <= event_end:
                refund_rate += extra
        refund_rate = float(np.clip(refund_rate * math.exp(rng.normal(0, 0.07)), 0.005, 0.62))

        refund_orders = int(round(channel_orders * refund_rate))
        refund_amount = round(refund_orders * aov * 0.92, 2)
        rows.append(
            (
                day.isoformat(),
                platform,
                category,
                channel,
                channel_orders,
                gmv,
                visitors,
                refund_orders,
                refund_amount,
            )
        )
    return rows


def build_fulfillment(sales: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """把每个 日期 × 平台 × 品类 的订单数按时效分桶拆开。

    用 multinomial 而不是独立四舍五入，保证各分桶订单数之和等于该组订单数，
    否则"48h 达成率"的分母会和销售表对不上。
    """
    grouped = sales.groupby(["date", "platform", "category"], as_index=False)["orders"].sum()
    pressure = _promo_pressure(sales)

    records: list[tuple[object, ...]] = []
    for row in grouped.itertuples():
        delay = pressure[(row.date, row.platform)]
        probabilities = _bucket_probabilities(row.platform, delay, rng)
        counts = rng.multinomial(int(row.orders), probabilities)
        for bucket, count in zip(SLA_BUCKETS, counts, strict=True):
            if count > 0:
                records.append((row.date, row.platform, row.category, bucket, int(count)))

    return pd.DataFrame(records, columns=list(FULFILLMENT_COLUMNS))


def _promo_pressure(sales: pd.DataFrame) -> dict[tuple[str, str], float]:
    """日期 × 平台 的履约压力（大促越高，时效越慢）。"""
    date_platform = sales.groupby(["date", "platform"], as_index=False)["orders"].sum()
    pressure: dict[tuple[str, str], float] = {}
    for row in date_platform.itertuples():
        intensity, _ = promo_intensity(date.fromisoformat(row.date), row.platform)
        pressure[(row.date, row.platform)] = min(0.42, 0.14 * max(0.0, intensity - 1.0))
    return pressure


def _bucket_probabilities(platform: str, delay: float, rng: np.random.Generator) -> np.ndarray:
    """按平台基线 + 促销压力，得到当日 5 个时效分桶的概率。"""
    base = np.array(SLA_PROFILE[platform], dtype=float)
    # 压力把 0-24h 的订单向 24h 之后迁移
    base[2] += delay * (base[0] * 0.45 + base[1] * 0.35)
    base[3] += delay * (base[1] * 0.15)
    base[4] += delay * (base[0] * 0.05)
    base[0] *= 1 - 0.45 * delay
    base[1] *= 1 - 0.30 * delay
    base += rng.normal(0, 0.008, 5).clip(min=0)
    base = np.clip(base, 1e-6, None)
    return base / base.sum()


def build_dim_date(start: date, end: date) -> pd.DataFrame:
    """日历维表：把周、季、促销标记预先算好，避免每个图表重复推导。"""
    records: list[tuple[object, ...]] = []
    for day in daterange(start, end):
        label = ""
        for name, promo_start, promo_end, _peak in PROMOS:
            if promo_start <= day <= promo_end:
                label = name
                break
        iso = day.isocalendar()
        records.append(
            (
                day.isoformat(),
                day.year,
                f"{day.year}Q{((day.month - 1) // 3) + 1}",
                day.month,
                f"{day.month}月",
                f"{iso.year}-W{iso.week:02d}",
                day.weekday() + 1,
                WEEKDAY_NAMES[day.weekday()],
                int(day.weekday() >= 5),
                int(bool(label)),
                label,
            )
        )
    return pd.DataFrame(records, columns=list(DIM_DATE_COLUMNS))


def generate_dataset(settings: Settings) -> dict[str, pd.DataFrame]:
    """一次生成三张表（同一 RNG 顺序，保证固定种子可复现）。"""
    rng = np.random.default_rng(settings.seed)
    logger.info("生成销售明细：%s ~ %s，seed=%s", settings.start, settings.end, settings.seed)
    sales = build_sales(settings.start, settings.end, rng)
    logger.info("销售明细 %s 行", f"{len(sales):,}")
    fulfillment = build_fulfillment(sales, rng)
    logger.info("履约分桶 %s 行", f"{len(fulfillment):,}")
    dim_date = build_dim_date(settings.start, settings.end)
    logger.info("日历维表 %s 行", f"{len(dim_date):,}")
    return {"fact_sales": sales, "fact_fulfillment": fulfillment, "dim_date": dim_date}


def write_dataset(frames: dict[str, pd.DataFrame], data_dir: Path) -> dict[str, Path]:
    """落盘为 CSV（UTF-8，无 BOM），返回文件名 → 路径。"""
    data_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for name, frame in frames.items():
        path = data_dir / f"{name}.csv"
        frame.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")
        written[name] = path
        logger.debug("写入 %s（%s 行）", path.name, f"{len(frame):,}")
    return written
