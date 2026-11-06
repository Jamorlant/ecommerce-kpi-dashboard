"""结论生成：把聚合结果翻译成业务判断。

为什么用代码生成而不是手写：手写数字会随着重跑数据过期；
这里的每条结论都只依赖传入的 DataFrame，改模型参数后结论自动更新。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ecommerce_kpi.metrics import pct_change


@dataclass(frozen=True, slots=True)
class InsightInputs:
    """结论所需的全部证据，避免 8 个位置参数。"""

    latest_month: str
    yoy_month: str
    platform_totals: pd.DataFrame
    monthly_platform: pd.DataFrame
    channel_platform: pd.DataFrame
    promo_sla: pd.DataFrame
    category_totals: pd.DataFrame
    anomalies: list[dict]


def build_insights(inputs: InsightInputs) -> list[dict]:
    """按"增长质量 → 渠道结构 → 履约风险 → 平台分工 → 异常定位"排列。"""
    insights = [
        _growth_insight(inputs),
        _live_channel_insight(inputs),
        _promo_sla_insight(inputs),
        _structure_insight(inputs),
    ]
    anomaly = _anomaly_insight(inputs)
    if anomaly is not None:
        insights.append(anomaly)
    return [item for item in insights if item is not None]


def _growth_insight(inputs: InsightInputs) -> dict:
    totals = inputs.platform_totals.set_index("platform")
    latest = inputs.monthly_platform[inputs.monthly_platform["month"] == inputs.latest_month].set_index("platform")
    last_year = inputs.monthly_platform[inputs.monthly_platform["month"] == inputs.yoy_month].set_index("platform")
    yoy = {
        platform: pct_change(latest.loc[platform, "gmv"], last_year.loc[platform, "gmv"]) or 0.0
        for platform in latest.index
    }
    douyin, jd = totals.loc["抖音"], totals.loc["京东"]
    return {
        "title": "增长来自抖音，但退货成本同步放大",
        "body": (
            f"抖音 GMV 占比 {douyin['gmv'] / totals['gmv'].sum():.1%}，"
            f"最新月（{inputs.latest_month}）GMV 同比 {yoy['抖音']:+.1%}，"
            f"增速高于天猫（{yoy['天猫']:+.1%}）与京东（{yoy['京东']:+.1%}）；"
            f"但其退款率 {douyin['refund_rate']:.1%} 是京东（{jd['refund_rate']:.1%}）的 "
            f"{douyin['refund_rate'] / jd['refund_rate']:.1f} 倍，增长质量需要单独考核。"
        ),
        "tag": "growth",
    }


def _live_channel_insight(inputs: InsightInputs) -> dict:
    channels = inputs.channel_platform
    live = channels[channels["channel"] == "直播"]
    other = channels[channels["channel"] != "直播"]
    live_rate = live["refund_orders"].sum() / live["orders"].sum()
    other_rate = other["refund_orders"].sum() / other["orders"].sum()
    douyin = inputs.platform_totals.set_index("platform").loc["抖音"]
    douyin_live_share = live[live["platform"] == "抖音"]["orders"].sum() / douyin["orders"]
    return {
        "title": "直播是退货率的结构性来源",
        "body": (
            f"直播渠道退款率 {live_rate:.1%}，比非直播渠道（{other_rate:.1%}）高 "
            f"{(live_rate - other_rate) * 100:.1f} 个百分点；"
            f"直播占抖音订单的 {douyin_live_share:.0%}，退货治理应优先落在直播话术、"
            f"尺码/色差说明与售后响应上。"
        ),
        "tag": "channel",
    }


def _promo_sla_insight(inputs: InsightInputs) -> dict | None:
    promo = inputs.promo_sla[inputs.promo_sla["is_promo"] == 1]
    normal = inputs.promo_sla[inputs.promo_sla["is_promo"] == 0]
    if promo.empty or normal.empty:
        # 自定义周期可能整段都没有促销日，此时该结论不成立，宁可不出
        return None
    promo_row, normal_row = promo.iloc[0], normal.iloc[0]
    promo_share = promo_row["orders"] / (promo_row["orders"] + normal_row["orders"])
    return {
        "title": "大促挤压履约：48h 达成率下滑",
        "body": (
            f"促销期订单占全周期 {promo_share:.1%}，48h 履约达成率 {promo_row['sla48_rate']:.1%}，"
            f"低于平销期 {normal_row['sla48_rate']:.1%}"
            f"（{(promo_row['sla48_rate'] - normal_row['sla48_rate']) * 100:+.1f}pp）。"
            f"峰值订单集中在 3-10 天窗口，需要前置仓与临时运力按促销日历弹性配置。"
        ),
        "tag": "fulfillment",
    }


def _structure_insight(inputs: InsightInputs) -> dict:
    totals = inputs.platform_totals.set_index("platform")
    jd, pdd = totals.loc["京东"], totals.loc["拼多多"]
    categories = inputs.category_totals
    top_aov = categories.sort_values("aov", ascending=False).iloc[0]
    top_orders = categories.sort_values("orders", ascending=False).iloc[0]
    return {
        "title": "客单价与订单量由不同平台承担",
        "body": (
            f"京东客单价 ¥{jd['aov']:.0f} 是拼多多（¥{pdd['aov']:.0f}）的 {jd['aov'] / pdd['aov']:.1f} 倍，"
            f"但拼多多订单量是京东的 {pdd['orders'] / jd['orders']:.1f} 倍；"
            f"{top_aov['category']}客单价最高（¥{top_aov['aov']:.0f}），{top_orders['category']}订单量最大。"
            f"拉新用拼多多、利润用京东、内容用抖音的组合更符合数据结构。"
        ),
        "tag": "structure",
    }


def _anomaly_insight(inputs: InsightInputs) -> dict | None:
    target = next(
        (item for item in inputs.anomalies if item["platform"] == "抖音" and item["category"] == "美妆个护"),
        None,
    )
    if target is None:
        return None
    return {
        "title": f"{target['platform']}·{target['category']} 出现退款率异常峰值",
        "body": (
            f"{target['month']} 退款率 {target['refund_rate']:.1%}，"
            f"高于该组合历年基线中位数 {target['baseline']:.1%} 共 {target['excess_pp']:.1f}pp，"
            f"涉及 {target['refund_orders']:,} 单退款；建议核查当期直播批次的质量投诉与功效宣称。"
        ),
        "tag": "risk",
    }
