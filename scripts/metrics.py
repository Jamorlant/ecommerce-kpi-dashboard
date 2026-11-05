"""
从合成数据计算电商核心指标，并导出看板所需的聚合数据。

指标口径（分子 / 分母）：
- GMV           = Σ 支付订单金额（下单口径，未扣退款）
- 订单量         = Σ 支付订单数
- 客单价         = GMV / 订单量
- 转化率         = 支付订单数 / 访客数（访客未跨渠道去重）
- 退款率         = 退款订单数 / 支付订单数（按原订单日期归因）
- 退款金额       = Σ 退款金额
- 48h 履约达成率  = (0-12h + 12-24h + 24-48h 分桶订单) / 总订单
- 加权履约时长   = Σ(分桶订单 × 分桶中值小时数) / 总订单，中值 6/18/36/60/96h
- 平台贡献占比   = 平台 GMV / 总 GMV
- 环比 / 同比     = (本期 - 对比期) / 对比期

运行：python scripts/metrics.py
输出：data/metrics.json（看板构建脚本与 README 引用）
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "metrics.json"

SLA_MIDPOINT = {"0-12h": 6, "12-24h": 18, "24-48h": 36, "48-72h": 60, "72h+": 96}
FAST_BUCKETS = {"0-12h", "12-24h", "24-48h"}


def pct(new: float, old: float) -> float | None:
    if old is None or old == 0 or np.isnan(old):
        return None
    return (new - old) / old


def aggregate(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    out = (
        df.groupby(keys, as_index=False)
        .agg(
            gmv=("gmv", "sum"),
            orders=("orders", "sum"),
            visitors=("visitors", "sum"),
            refund_orders=("refund_orders", "sum"),
            refund_amount=("refund_amount", "sum"),
        )
    )
    out["aov"] = out["gmv"] / out["orders"]
    out["cvr"] = out["orders"] / out["visitors"]
    out["refund_rate"] = out["refund_orders"] / out["orders"]
    return out


def sla_metrics(f: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    f = f.copy()
    f["fast48"] = f["sla_bucket"].isin(FAST_BUCKETS).astype(int)
    f["hours"] = f["sla_bucket"].map(SLA_MIDPOINT)
    f["fast48_orders"] = f["orders"] * f["fast48"]
    f["hours_weighted"] = f["orders"] * f["hours"]
    out = (
        f.groupby(keys, as_index=False)
        .agg(sla_orders=("orders", "sum"), fast48_orders=("fast48_orders", "sum"), hours_weighted=("hours_weighted", "sum"))
    )
    out["sla48_rate"] = out["fast48_orders"] / out["sla_orders"]
    out["avg_hours"] = out["hours_weighted"] / out["sla_orders"]
    return out


def main() -> None:
    sales = pd.read_csv(DATA / "fact_sales.csv", parse_dates=["date"])
    fulfill = pd.read_csv(DATA / "fact_fulfillment.csv", parse_dates=["date"])
    dim = pd.read_csv(DATA / "dim_date.csv", parse_dates=["date"])

    sales["month"] = sales["date"].dt.strftime("%Y-%m")
    fulfill["month"] = fulfill["date"].dt.strftime("%Y-%m")

    months = sorted(sales["month"].unique())
    latest, prev, yoy = months[-1], months[-2], months[-13]
    platforms = sorted(sales["platform"].unique())
    categories = sorted(sales["category"].unique())
    channels = sorted(sales["channel"].unique())

    # 月度 × 平台（含履约）
    mp = aggregate(sales, ["month", "platform"])
    mp = mp.merge(
        sla_metrics(fulfill, ["month", "platform"])[["month", "platform", "sla_orders", "fast48_orders", "hours_weighted", "sla48_rate", "avg_hours"]],
        on=["month", "platform"],
        how="left",
    )

    # 月度 × 平台 × 品类（用于退货异常检测）
    mpc = aggregate(sales, ["month", "platform", "category"])
    mpc["refund_rate"] = mpc["refund_orders"] / mpc["orders"]

    # 全期结构
    platform_totals = aggregate(sales, ["platform"]).merge(
        sla_metrics(fulfill, ["platform"])[["platform", "sla48_rate", "avg_hours"]], on="platform", how="left"
    )
    platform_totals["gmv_share"] = platform_totals["gmv"] / platform_totals["gmv"].sum()

    cat_platform = aggregate(sales, ["platform", "category"])
    channel_platform = aggregate(sales, ["platform", "channel"])

    sla_dist = fulfill.groupby(["platform", "sla_bucket"], as_index=False)["orders"].sum()
    sla_dist["share"] = sla_dist["orders"] / sla_dist.groupby("platform")["orders"].transform("sum")

    # 促销 vs 平销履约
    fulfill_promo = fulfill.merge(dim[["date", "is_promo", "promo_name"]], on="date", how="left")
    fulfill_promo["is_promo"] = fulfill_promo["is_promo"].fillna(0).astype(int)
    fulfill_promo["fast48_orders"] = fulfill_promo["orders"] * fulfill_promo["sla_bucket"].isin(FAST_BUCKETS).astype(int)
    promo_sla = (
        fulfill_promo.groupby("is_promo")
        .agg(orders=("orders", "sum"), fast48_orders=("fast48_orders", "sum"))
        .assign(sla48_rate=lambda d: d["fast48_orders"] / d["orders"])
        .reset_index()
    )

    # 日粒度趋势（按平台）
    daily = sales.groupby(["date", "platform"], as_index=False)["gmv"].sum()
    daily["date"] = daily["date"].dt.strftime("%Y-%m-%d")

    # ---- 核心 KPI（最新完整月）----
    def kpi_block(m: str) -> dict:
        d = sales[sales["month"] == m]
        agg = aggregate(d, ["platform"])
        tot = agg.sum(numeric_only=True)
        sla = sla_metrics(fulfill[fulfill["month"] == m], ["platform"])
        sla48 = sla["fast48_orders"].sum() / sla["sla_orders"].sum()
        hours = sla["hours_weighted"].sum() / sla["sla_orders"].sum()
        return {
            "gmv": float(tot["gmv"]),
            "orders": float(tot["orders"]),
            "visitors": float(tot["visitors"]),
            "aov": float(tot["gmv"] / tot["orders"]),
            "cvr": float(tot["orders"] / tot["visitors"]),
            "refund_rate": float(tot["refund_orders"] / tot["orders"]),
            "refund_amount": float(tot["refund_amount"]),
            "sla48": float(sla48),
            "avg_hours": float(hours),
        }

    cur, before, last_year = kpi_block(latest), kpi_block(prev), kpi_block(yoy)

    kpis = [
        {"key": "gmv", "label": "GMV（月度）", "value": cur["gmv"], "unit": "currency", "mom": pct(cur["gmv"], before["gmv"]), "yoy": pct(cur["gmv"], last_year["gmv"]), "hint": "支付口径成交额"},
        {"key": "orders", "label": "订单量", "value": cur["orders"], "unit": "count", "mom": pct(cur["orders"], before["orders"]), "yoy": pct(cur["orders"], last_year["orders"]), "hint": "支付订单数"},
        {"key": "aov", "label": "客单价", "value": cur["aov"], "unit": "currency", "mom": pct(cur["aov"], before["aov"]), "yoy": pct(cur["aov"], last_year["aov"]), "hint": "GMV / 订单量"},
        {"key": "cvr", "label": "支付转化率", "value": cur["cvr"], "unit": "percent", "mom": pct(cur["cvr"], before["cvr"]), "yoy": pct(cur["cvr"], last_year["cvr"]), "hint": "订单量 / 访客数"},
        {"key": "refund_rate", "label": "退款率", "value": cur["refund_rate"], "unit": "percent", "mom": pct(cur["refund_rate"], before["refund_rate"]), "yoy": pct(cur["refund_rate"], last_year["refund_rate"]), "hint": "退款订单 / 支付订单，越低越好", "inverse": True},
        {"key": "sla48", "label": "48h 履约达成率", "value": cur["sla48"], "unit": "percent", "mom": pct(cur["sla48"], before["sla48"]), "yoy": pct(cur["sla48"], last_year["sla48"]), "hint": "48h 内出库订单占比", "inverse": False},
    ]

    # ---- 退货率异常检测：月度平台×品类 对比其前 3 个月中位数 ----
    anomalies = []
    for (p, c), grp in mpc.groupby(["platform", "category"]):
        grp = grp.sort_values("month").reset_index(drop=True)
        for i in range(2, len(grp)):
            baseline = float(grp.loc[max(0, i - 3) : i - 1, "refund_rate"].median())
            rate = float(grp.loc[i, "refund_rate"])
            excess = rate - baseline
            # 同时满足：绝对抬升 ≥ 2.5pp，且相对基线 ≥ 18%，避免把普涨误判为异常
            if excess < 0.025 or rate < baseline * 1.18:
                continue
            row = grp.loc[i]
            anomalies.append(
                {
                    "platform": p,
                    "category": c,
                    "month": row["month"],
                    "refund_rate": rate,
                    "baseline": baseline,
                    "excess_pp": excess * 100,
                    "orders": int(row["orders"]),
                    "refund_orders": int(row["refund_orders"]),
                    "severity": "high" if excess >= 0.05 else "medium",
                }
            )
    anomalies.sort(key=lambda x: x["excess_pp"], reverse=True)

    # ---- 结论（全部由数据计算，避免手写数字）----
    def share(p: str, col: str = "gmv") -> float:
        row = platform_totals[platform_totals["platform"] == p].iloc[0]
        return float(row[col] / platform_totals[col].sum())

    # 同比增长（最新完整月 vs 去年同月，季节可比）
    latest_rows = mp[mp["month"] == latest].set_index("platform")
    yoy_rows = mp[mp["month"] == yoy].set_index("platform")
    yoy_growth = {p: float(latest_rows.loc[p, "gmv"] / yoy_rows.loc[p, "gmv"] - 1) for p in platforms}

    live = channel_platform[channel_platform["channel"] == "直播"].copy()
    live_rate = live["refund_orders"].sum() / live["orders"].sum()
    other = channel_platform[channel_platform["channel"] != "直播"]
    other_rate = other["refund_orders"].sum() / other["orders"].sum()

    jd = platform_totals[platform_totals["platform"] == "京东"].iloc[0]
    pdd = platform_totals[platform_totals["platform"] == "拼多多"].iloc[0]
    dy = platform_totals[platform_totals["platform"] == "抖音"].iloc[0]
    tm = platform_totals[platform_totals["platform"] == "天猫"].iloc[0]
    dy_live_share = live[live["platform"] == "抖音"]["orders"].sum() / dy["orders"]

    promo_row = promo_sla[promo_sla["is_promo"] == 1].iloc[0]
    normal_row = promo_sla[promo_sla["is_promo"] == 0].iloc[0]
    promo_share = promo_row["orders"] / (promo_row["orders"] + normal_row["orders"])


    cat_tot = sales.groupby("category", as_index=False).agg(gmv=("gmv", "sum"), orders=("orders", "sum"))
    cat_tot["aov"] = cat_tot["gmv"] / cat_tot["orders"]
    top_gmv_cat = cat_tot.sort_values("gmv", ascending=False).iloc[0]
    top_aov_cat = cat_tot.sort_values("aov", ascending=False).iloc[0]
    top_orders_cat = cat_tot.sort_values("orders", ascending=False).iloc[0]

    beauty_anomaly = next((a for a in anomalies if a["platform"] == "抖音" and a["category"] == "美妆个护"), None)

    insights = [
        {
            "title": "增长来自抖音，但退货成本同步放大",
            "body": (
                f"抖音 GMV 占比 {share('抖音'):.1%}，最新月（{latest}）GMV 同比 {yoy_growth['抖音']:+.1%}，"
                f"增速高于天猫（{yoy_growth['天猫']:+.1%}）与京东（{yoy_growth['京东']:+.1%}）；"
                f"但其退款率 {dy['refund_rate']:.1%} 是京东（{jd['refund_rate']:.1%}）的 {dy['refund_rate'] / jd['refund_rate']:.1f} 倍，"
                f"增长质量需要单独考核。"
            ),
            "tag": "growth",
        },
        {
            "title": "直播是退货率的结构性来源",
            "body": (
                f"直播渠道退款率 {live_rate:.1%}，比非直播渠道（{other_rate:.1%}）高 {(live_rate - other_rate) * 100:.1f} 个百分点；"
                f"直播占抖音订单的 {dy_live_share:.0%}，退货治理应优先落在直播话术、尺码/色差说明与售后响应上。"
            ),
            "tag": "channel",
        },
        {
            "title": "大促挤压履约：48h 达成率下滑",
            "body": (
                f"促销期订单占全周期 {promo_share:.1%}，48h 履约达成率 {promo_row['sla48_rate']:.1%}，"
                f"低于平销期 {normal_row['sla48_rate']:.1%}（{(promo_row['sla48_rate'] - normal_row['sla48_rate']) * 100:+.1f}pp）。"
                f"峰值订单集中在 3-10 天窗口，需要前置仓与临时运力按促销日历弹性配置。"
            ),
            "tag": "fulfillment",
        },
        {
            "title": "客单价与订单量由不同平台承担",
            "body": (
                f"京东客单价 ¥{jd['aov']:.0f} 是拼多多（¥{pdd['aov']:.0f}）的 {jd['aov'] / pdd['aov']:.1f} 倍，"
                f"但拼多多订单量是京东的 {pdd['orders'] / jd['orders']:.1f} 倍；"
                f"{top_aov_cat['category']}客单价最高（¥{top_aov_cat['aov']:.0f}），{top_orders_cat['category']}订单量最大。"
                f"拉新用拼多多、利润用京东、内容用抖音的组合更符合数据结构。"
            ),
            "tag": "structure",
        },
    ]
    if beauty_anomaly:
        insights.append(
            {
                "title": f"{beauty_anomaly['platform']}·{beauty_anomaly['category']} 出现退款率异常峰值",
                "body": (
                    f"{beauty_anomaly['month']} 退款率 {beauty_anomaly['refund_rate']:.1%}，"
                    f"高于该组合历年基线中位数 {beauty_anomaly['baseline']:.1%} 共 {beauty_anomaly['excess_pp']:.1f}pp，"
                    f"涉及 {beauty_anomaly['refund_orders']:,} 单退款；建议核查当期直播批次的质量投诉与功效宣称。"
                ),
                "tag": "risk",
            }
        )

    def records(df: pd.DataFrame, cols: list[str]) -> list[dict]:
        return df[cols].round(6).to_dict(orient="records")

    # 促销窗口（连续日期合并）
    dim_sorted = dim.sort_values("date")
    promo_windows = []
    current = None
    for r in dim_sorted.itertuples():
        if r.is_promo:
            if current and current["name"] == r.promo_name and (r.date - current["end_date"]).days == 1:
                current["end"] = r.date.strftime("%Y-%m-%d")
                current["end_date"] = r.date
            else:
                current = {
                    "name": r.promo_name,
                    "start": r.date.strftime("%Y-%m-%d"),
                    "end": r.date.strftime("%Y-%m-%d"),
                    "end_date": r.date,
                }
                promo_windows.append(current)
        else:
            current = None
    for w in promo_windows:
        w.pop("end_date", None)

    payload = {
        "meta": {
            "period_start": str(sales["date"].min().date()),
            "period_end": str(sales["date"].max().date()),
            "months": months,
            "latest_month": latest,
            "prev_month": prev,
            "yoy_month": yoy,
            "platforms": platforms,
            "categories": categories,
            "channels": channels,
            "promo_windows": promo_windows,
            "rows": int(len(sales)),
            "orders_total": int(sales["orders"].sum()),
            "gmv_total": float(sales["gmv"].sum()),
            "generated_at": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M"),
            "data_note": "全部为脚本生成的合成数据，不含任何真实企业、客户或个人信息。",
        },
        "kpis": kpis,
        "monthly_platform": records(
            mp, ["month", "platform", "gmv", "orders", "visitors", "refund_orders", "refund_amount", "aov", "cvr", "refund_rate", "sla48_rate", "avg_hours", "sla_orders", "fast48_orders"]
        ),
        "monthly_platform_category": records(mpc, ["month", "platform", "category", "gmv", "orders", "refund_orders"]),
        "platform_totals": records(
            platform_totals, ["platform", "gmv", "orders", "visitors", "refund_orders", "refund_amount", "aov", "cvr", "refund_rate", "sla48_rate", "avg_hours", "gmv_share"]
        ),
        "category_platform": records(cat_platform, ["platform", "category", "gmv", "orders", "refund_orders", "aov", "refund_rate"]),
        "channel_platform": records(channel_platform, ["platform", "channel", "gmv", "orders", "refund_orders", "aov", "refund_rate"]),
        "sla_distribution": records(sla_dist, ["platform", "sla_bucket", "orders", "share"]),
        "sla_promo": records(promo_sla, ["is_promo", "orders", "fast48_orders", "sla48_rate"]),
        "daily_platform": daily.to_dict(orient="records"),
        "anomalies": anomalies[:6],
        "insights": insights,
        "category_totals": records(cat_tot, ["category", "gmv", "orders", "aov"]),
    }

    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=float), encoding="utf-8")

    # 控制台摘要
    print(f"周期 {payload['meta']['period_start']} ~ {payload['meta']['period_end']}  |  行数 {len(sales):,}  |  GMV {payload['meta']['gmv_total'] / 1e8:.2f} 亿元")
    print(f"最新完整月 {latest}：GMV {cur['gmv'] / 1e8:.2f} 亿  环比 {kpis[0]['mom']:+.1%}  同比 {kpis[0]['yoy']:+.1%}")
    print("\n平台结构：")
    for p in platform_totals.itertuples():
        print(f"  {p.platform:<4} GMV {p.gmv / 1e8:>4.2f}亿  占比 {p.gmv_share:>5.1%}  客单价 ¥{p.aov:>6.0f}  退款率 {p.refund_rate:>5.1%}  48h {p.sla48_rate:>5.1%}")
    print("\n退货率异常：")
    for a in anomalies[:6]:
        print(f"  {a['month']} {a['platform']}·{a['category']}  退款率 {a['refund_rate']:.1%}  基线 {a['baseline']:.1%}  超出 {a['excess_pp']:.1f}pp")
    print(f"\n输出：{OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
