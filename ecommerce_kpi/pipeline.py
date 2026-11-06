"""流水线编排：读入事实表 → 计算 → 输出 data/metrics.json。

为什么把编排和计算分开：metrics.py / anomalies.py 是纯函数，测试不需要碰文件；
这里负责 I/O、校验、日志与产物落盘。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from ecommerce_kpi.anomalies import detect_anomalies
from ecommerce_kpi.config import ROOT, Settings
from ecommerce_kpi.errors import DataContractError
from ecommerce_kpi.insights import InsightInputs, build_insights
from ecommerce_kpi.metrics import (
    FAST_BUCKETS,
    add_month_column,
    aggregate,
    pct_change,
    records,
    sla_metrics,
)
from ecommerce_kpi.scenario import DIM_DATE_COLUMNS, FULFILLMENT_COLUMNS, SALES_COLUMNS
from ecommerce_kpi.validate import order_consistency_gap, validate_frame

logger = logging.getLogger(__name__)

# 同比需要"最新月 + 去年同月"，即至少 13 个自然月；不足时宁可报错也不算出假 -100%
MIN_MONTHS_FOR_YOY = 13
SALES_NUMERIC = ("orders", "gmv", "visitors", "refund_orders", "refund_amount")
FULFILLMENT_NUMERIC = ("orders",)
DIM_NUMERIC = ("is_promo",)


def build_payload(sales: pd.DataFrame, fulfillment: pd.DataFrame, dim_date: pd.DataFrame) -> dict:
    """把三张表折算成看板消费的一份 JSON。"""
    sales = add_month_column(sales)
    fulfillment = add_month_column(fulfillment)

    months = sorted(sales["month"].unique())
    if len(months) < MIN_MONTHS_FOR_YOY:
        raise DataContractError(
            f"仅 {len(months)} 个完整月，无法计算同比（需要 ≥{MIN_MONTHS_FOR_YOY} 个月）"
            "；请调整 KPI_START_DATE / KPI_END_DATE"
        )
    latest, previous, last_year = months[-1], months[-2], months[-13]

    monthly_platform = _monthly_platform(sales, fulfillment)
    monthly_platform_category = _monthly_platform_category(sales)
    platform_totals = _platform_totals(sales, fulfillment)
    category_platform = aggregate(sales, ["platform", "category"])
    channel_platform = aggregate(sales, ["platform", "channel"])
    category_totals = aggregate(sales, ["category"])
    sla_distribution = _sla_distribution(fulfillment)
    promo_sla = _promo_sla(fulfillment, dim_date)
    daily_platform = _daily_platform(sales)

    anomalies = detect_anomalies(monthly_platform_category)
    if anomalies:
        logger.warning(
            "退款率异常命中 %s 条；最高 %s %s·%s +%.1fpp",
            len(anomalies),
            anomalies[0]["month"],
            anomalies[0]["platform"],
            anomalies[0]["category"],
            anomalies[0]["excess_pp"],
        )

    insights = build_insights(
        InsightInputs(
            latest_month=latest,
            yoy_month=last_year,
            platform_totals=platform_totals,
            monthly_platform=monthly_platform,
            channel_platform=channel_platform,
            promo_sla=promo_sla,
            category_totals=category_totals,
            anomalies=anomalies,
        )
    )

    payload = {
        "meta": {
            "period_start": str(sales["date"].min().date()),
            "period_end": str(sales["date"].max().date()),
            "months": months,
            "latest_month": latest,
            "prev_month": previous,
            "yoy_month": last_year,
            "platforms": sorted(sales["platform"].unique()),
            "categories": sorted(sales["category"].unique()),
            "channels": sorted(sales["channel"].unique()),
            "promo_windows": build_promo_windows(dim_date),
            "rows": int(len(sales)),
            "orders_total": int(sales["orders"].sum()),
            "gmv_total": float(sales["gmv"].sum()),
            "data_note": "全部为脚本生成的合成数据，不含任何真实企业、客户或个人信息。",
        },
        "kpis": _kpis(sales, fulfillment, latest, previous, last_year),
        "monthly_platform": records(
            monthly_platform,
            [
                "month",
                "platform",
                "gmv",
                "orders",
                "visitors",
                "refund_orders",
                "refund_amount",
                "aov",
                "cvr",
                "refund_rate",
                "sla48_rate",
                "avg_hours",
                "sla_orders",
                "fast48_orders",
            ],
        ),
        "monthly_platform_category": records(
            monthly_platform_category, ["month", "platform", "category", "gmv", "orders", "refund_orders"]
        ),
        "platform_totals": records(
            platform_totals,
            [
                "platform",
                "gmv",
                "orders",
                "visitors",
                "refund_orders",
                "refund_amount",
                "aov",
                "cvr",
                "refund_rate",
                "sla48_rate",
                "avg_hours",
                "gmv_share",
            ],
        ),
        "category_platform": records(
            category_platform, ["platform", "category", "gmv", "orders", "refund_orders", "aov", "refund_rate"]
        ),
        "channel_platform": records(
            channel_platform, ["platform", "channel", "gmv", "orders", "refund_orders", "aov", "refund_rate"]
        ),
        "sla_distribution": records(sla_distribution, ["platform", "sla_bucket", "orders", "share"]),
        "sla_promo": records(promo_sla, ["is_promo", "orders", "fast48_orders", "sla48_rate"]),
        "daily_platform": daily_platform.to_dict(orient="records"),
        "anomalies": anomalies,
        "insights": insights,
        "category_totals": records(category_totals, ["category", "gmv", "orders", "aov"]),
    }
    return payload


def _monthly_platform(sales: pd.DataFrame, fulfillment: pd.DataFrame) -> pd.DataFrame:
    merged = aggregate(sales, ["month", "platform"]).merge(
        sla_metrics(fulfillment, ["month", "platform"])[
            ["month", "platform", "sla_orders", "fast48_orders", "hours_weighted", "sla48_rate", "avg_hours"]
        ],
        on=["month", "platform"],
        how="left",
    )
    return merged


def _monthly_platform_category(sales: pd.DataFrame) -> pd.DataFrame:
    frame = aggregate(sales, ["month", "platform", "category"])
    frame["refund_rate"] = frame["refund_orders"] / frame["orders"]
    return frame


def _platform_totals(sales: pd.DataFrame, fulfillment: pd.DataFrame) -> pd.DataFrame:
    totals = aggregate(sales, ["platform"]).merge(
        sla_metrics(fulfillment, ["platform"])[["platform", "sla48_rate", "avg_hours"]],
        on="platform",
        how="left",
    )
    totals["gmv_share"] = totals["gmv"] / totals["gmv"].sum()
    return totals


def _sla_distribution(fulfillment: pd.DataFrame) -> pd.DataFrame:
    frame = fulfillment.groupby(["platform", "sla_bucket"], as_index=False)["orders"].sum()
    frame["share"] = frame["orders"] / frame.groupby("platform")["orders"].transform("sum")
    return frame


def _promo_sla(fulfillment: pd.DataFrame, dim_date: pd.DataFrame) -> pd.DataFrame:
    """促销期 vs 平销期的履约达成率对比。"""
    frame = fulfillment.merge(dim_date[["date", "is_promo", "promo_name"]], on="date", how="left")
    frame["is_promo"] = frame["is_promo"].fillna(0).astype(int)
    frame["fast48_orders"] = frame["orders"] * frame["sla_bucket"].isin(FAST_BUCKETS).astype(int)
    return (
        frame.groupby("is_promo", as_index=False)
        .agg(orders=("orders", "sum"), fast48_orders=("fast48_orders", "sum"))
        .assign(sla48_rate=lambda data: data["fast48_orders"] / data["orders"])
    )


def _daily_platform(sales: pd.DataFrame) -> pd.DataFrame:
    daily = sales.groupby(["date", "platform"], as_index=False)["gmv"].sum()
    daily["date"] = daily["date"].dt.strftime("%Y-%m-%d")
    return daily


def _kpis(sales: pd.DataFrame, fulfillment: pd.DataFrame, latest: str, previous: str, last_year: str) -> list[dict]:
    """6 张 KPI 卡：最新完整月 vs 上月 vs 去年同月。"""
    current = _kpi_block(sales, fulfillment, latest)
    before = _kpi_block(sales, fulfillment, previous)
    yoy = _kpi_block(sales, fulfillment, last_year)
    return [
        {
            "key": "gmv",
            "label": "GMV（月度）",
            "value": current["gmv"],
            "unit": "currency",
            "mom": pct_change(current["gmv"], before["gmv"]),
            "yoy": pct_change(current["gmv"], yoy["gmv"]),
            "hint": "支付口径成交额",
        },
        {
            "key": "orders",
            "label": "订单量",
            "value": current["orders"],
            "unit": "count",
            "mom": pct_change(current["orders"], before["orders"]),
            "yoy": pct_change(current["orders"], yoy["orders"]),
            "hint": "支付订单数",
        },
        {
            "key": "aov",
            "label": "客单价",
            "value": current["aov"],
            "unit": "currency",
            "mom": pct_change(current["aov"], before["aov"]),
            "yoy": pct_change(current["aov"], yoy["aov"]),
            "hint": "GMV / 订单量",
        },
        {
            "key": "cvr",
            "label": "支付转化率",
            "value": current["cvr"],
            "unit": "percent",
            "mom": pct_change(current["cvr"], before["cvr"]),
            "yoy": pct_change(current["cvr"], yoy["cvr"]),
            "hint": "订单量 / 访客数",
        },
        {
            "key": "refund_rate",
            "label": "退款率",
            "value": current["refund_rate"],
            "unit": "percent",
            "mom": pct_change(current["refund_rate"], before["refund_rate"]),
            "yoy": pct_change(current["refund_rate"], yoy["refund_rate"]),
            "hint": "退款订单 / 支付订单，越低越好",
            "inverse": True,
        },
        {
            "key": "sla48",
            "label": "48h 履约达成率",
            "value": current["sla48"],
            "unit": "percent",
            "mom": pct_change(current["sla48"], before["sla48"]),
            "yoy": pct_change(current["sla48"], yoy["sla48"]),
            "hint": "48h 内出库订单占比",
            "inverse": False,
        },
    ]


def _kpi_block(sales: pd.DataFrame, fulfillment: pd.DataFrame, month: str) -> dict[str, float]:
    month_sales = sales[sales["month"] == month]
    totals = aggregate(month_sales, ["platform"]).sum(numeric_only=True)
    month_sla = sla_metrics(fulfillment[fulfillment["month"] == month], ["platform"])
    return {
        "gmv": float(totals["gmv"]),
        "orders": float(totals["orders"]),
        "visitors": float(totals["visitors"]),
        "aov": float(totals["gmv"] / totals["orders"]),
        "cvr": float(totals["orders"] / totals["visitors"]),
        "refund_rate": float(totals["refund_orders"] / totals["orders"]),
        "refund_amount": float(totals["refund_amount"]),
        "sla48": float(month_sla["fast48_orders"].sum() / month_sla["sla_orders"].sum()),
        "avg_hours": float(month_sla["hours_weighted"].sum() / month_sla["sla_orders"].sum()),
    }


def build_promo_windows(dim_date: pd.DataFrame) -> list[dict]:
    """把连续促销日合并成窗口，供 ECharts 的 markArea 使用。"""
    windows: list[dict] = []
    current: dict | None = None
    for row in dim_date.sort_values("date").itertuples():
        if not row.is_promo:
            current = None
            continue
        if current and current["name"] == row.promo_name and (row.date - current["end_date"]).days == 1:
            current["end"] = row.date.strftime("%Y-%m-%d")
            current["end_date"] = row.date
            continue
        current = {
            "name": row.promo_name,
            "start": row.date.strftime("%Y-%m-%d"),
            "end": row.date.strftime("%Y-%m-%d"),
            "end_date": row.date,
        }
        windows.append(current)
    return [{"name": item["name"], "start": item["start"], "end": item["end"]} for item in windows]


def run_metrics(settings: Settings) -> Path:
    """读 CSV → 校验 → 计算 → 写 data/metrics.json。"""
    data_dir = settings.data_dir
    sales = pd.read_csv(data_dir / "fact_sales.csv", parse_dates=["date"])
    fulfillment = pd.read_csv(data_dir / "fact_fulfillment.csv", parse_dates=["date"])
    dim_date = pd.read_csv(data_dir / "dim_date.csv", parse_dates=["date"])

    validate_frame(
        "fact_sales",
        sales,
        columns=SALES_COLUMNS,
        numeric=SALES_NUMERIC,
        date_columns=("date",),
    )
    validate_frame(
        "fact_fulfillment",
        fulfillment,
        columns=FULFILLMENT_COLUMNS,
        numeric=FULFILLMENT_NUMERIC,
        date_columns=("date",),
    )
    validate_frame(
        "dim_date",
        dim_date,
        columns=DIM_DATE_COLUMNS,
        numeric=DIM_NUMERIC,
        date_columns=("date",),
    )

    gap = order_consistency_gap(sales, fulfillment)
    if gap > 0.001:
        logger.warning("履约分桶订单数与销售订单数偏差 %.2f%%，请检查数据来源", gap * 100)
    else:
        logger.debug("履约分桶与销售订单数一致（偏差 %.4f%%）", gap * 100)

    payload = build_payload(sales, fulfillment, dim_date)
    out = data_dir / "metrics.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=float), encoding="utf-8")

    meta = payload["meta"]
    logger.info(
        "指标完成：%s ~ %s，%s 行，GMV %.2f 亿元 → %s",
        meta["period_start"],
        meta["period_end"],
        meta["rows"],
        meta["gmv_total"] / 1e8,
        out.relative_to(ROOT) if out.is_relative_to(ROOT) else out,
    )
    for item in payload["platform_totals"]:
        logger.info(
            "  %-4s GMV %.2f 亿  占比 %5.1f%%  客单价 ¥%4.0f  退款率 %5.1f%%  48h %5.1f%%",
            item["platform"],
            item["gmv"] / 1e8,
            item["gmv_share"] * 100,
            item["aov"],
            item["refund_rate"] * 100,
            item["sla48_rate"] * 100,
        )
    return out
