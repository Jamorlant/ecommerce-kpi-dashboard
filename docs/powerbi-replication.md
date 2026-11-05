# 在 Power BI Desktop 中复刻这份看板

本文件给出把 `data/*.csv` 复刻成与 `dashboard/index.html` 等价看板的完整步骤：表关系、日期表、度量值、页面布局与校验值。按顺序操作即可，无需额外数据。

## 1. 前提

- Power BI Desktop（2023 年及以后版本均可），中文界面。
- 已运行 `python scripts/generate_data.py`，`data/` 下有三个 CSV。
- 数据是合成数据，仅用于演示，见 README 的数据说明。

## 2. 导入数据

1. `主页 → 获取数据 → 文本/CSV`，分别导入 `fact_sales.csv`、`fact_fulfillment.csv`、`dim_date.csv`。
2. 在 Power Query 中确认：
   - `date` 列类型为**日期**；`gmv`、`refund_amount`、`aov`、`cvr` 等为**小数**；订单数、访客数为**整数**。
   - `fact_sales` 重命名为 `fact_sales`，`fact_fulfillment` 重命名为 `fact_fulfillment`，`dim_date` 重命名为 `dim_date`。
3. 新建三个维度表（推荐"引用"事实表后删除其他列并去重）：
   - `dim_platform`：`platform` 一列。
   - `dim_category`：`category` 一列。
   - `dim_channel`：`channel` 一列。
4. 为 `fact_fulfillment` 增加一个计算列 `hours`（分桶中值，用于加权履约时长）：

```DAX
hours =
SWITCH(
    fact_fulfillment[sla_bucket],
    "0-12h", 6,
    "12-24h", 18,
    "24-48h", 36,
    "48-72h", 60,
    96
)
```

5. 为 `dim_date` 增加 `year_month = FORMAT(dim_date[date], "YYYY-MM")`，并按 `month_no` 对 `month_name` 做"按列排序"，避免月份按字母排序。

## 3. 表关系（星型模型）

```
                    dim_date (1) ─────────────┐
                                              │
 dim_platform (1) ──< fact_sales >── dim_category (1)
                          │      └── dim_channel (1)
                          │
                          └── (同 date / platform / category 维度)
                    dim_date (1) ──< fact_fulfillment >── dim_platform (1)
                                                        └── dim_category (1)
```

在"模型视图"中建立以下关系，全部为**一对多、单向筛选**（维度 → 事实）：

| 从 | 到 | 键 |
| --- | --- | --- |
| dim_date[date] | fact_sales[date] | date |
| dim_date[date] | fact_fulfillment[date] | date |
| dim_platform[platform] | fact_sales[platform] | platform |
| dim_category[category] | fact_sales[category] | category |
| dim_channel[channel] | fact_sales[channel] | channel |
| dim_platform[platform] | fact_fulfillment[platform] | platform |
| dim_category[category] | fact_fulfillment[category] | category |

最后选中 `dim_date` → 右键 → **标记为日期表**，标记列 `date`。

## 4. 核心度量值

新建空表 `_measures` 或直接建在 `fact_sales` 上，以下度量值按"基础 → 时间 → 结构 → 异常"分组。Power BI 允许中文度量值名。

### 4.1 基础指标

```DAX
GMV = SUM ( fact_sales[gmv] )

订单量 = SUM ( fact_sales[orders] )

访客数 = SUM ( fact_sales[visitors] )

退款订单数 = SUM ( fact_sales[refund_orders] )

退款金额 = SUM ( fact_sales[refund_amount] )

客单价 = DIVIDE ( [GMV], [订单量] )

支付转化率 = DIVIDE ( [订单量], [访客数] )

退款率 = DIVIDE ( [退款订单数], [订单量] )
```

> 口径与 README 一致：GMV 为支付口径且不扣退款；退款率按原订单日期归因。

### 4.2 履约时效

```DAX
履约订单量 = SUM ( fact_fulfillment[orders] )

48h 履约订单 =
CALCULATE (
    SUM ( fact_fulfillment[orders] ),
    fact_fulfillment[sla_bucket] IN { "0-12h", "12-24h", "24-48h" }
)

48h 履约达成率 = DIVIDE ( [48h 履约订单], [履约订单量] )

加权履约时长 =
DIVIDE (
    SUMX ( fact_fulfillment, fact_fulfillment[orders] * fact_fulfillment[hours] ),
    [履约订单量]
)
```

### 4.3 时间对比（环比 / 同比）

```DAX
环比 GMV =
VAR cur = [GMV]
VAR prev = CALCULATE ( [GMV], DATEADD ( dim_date[date], -1, MONTH ) )
RETURN DIVIDE ( cur - prev, prev )

同比 GMV =
VAR py = CALCULATE ( [GMV], SAMEPERIODLASTYEAR ( dim_date[date] ) )
RETURN DIVIDE ( [GMV] - py, py )

环比 退款率 =
VAR cur = [退款率]
VAR prev = CALCULATE ( [退款率], DATEADD ( dim_date[date], -1, MONTH ) )
RETURN DIVIDE ( cur - prev, prev )
```

把 `[GMV]` 换成 `[订单量]`、`[客单价]`、`[支付转化率]`、`[48h 履约达成率]` 即可得到对应的环比/同比度量值。

> 注意：`DATEADD` / `SAMEPERIODLASTYEAR` 依赖已标记的日期表，且页面需有日期或月份切片器；KPI 卡片请将页面筛选设为最新完整月 `2025-08`，否则会按当前筛选区间计算。

### 4.4 结构占比与排名

```DAX
平台 GMV 占比 =
DIVIDE ( [GMV], CALCULATE ( [GMV], REMOVEFILTERS ( dim_platform ) ) )

品类 GMV 占比 =
DIVIDE ( [GMV], CALCULATE ( [GMV], REMOVEFILTERS ( dim_category ) ) )

品类 GMV 排名 =
RANKX ( ALLSELECTED ( dim_category[category] ), [GMV], , DESC, DENSE )

渠道退款率 = DIVIDE ( CALCULATE ( [退款订单数] ), CALCULATE ( [订单量] ) )
```

### 4.5 退款率异常标记（对应看板"异常预警"面板）

以"当前月份的前 3 个完整月"为基线，同时要求绝对抬升 ≥ 2.5pp、相对抬升 ≥ 18%：

```DAX
退款率前 3 月基线 =
VAR curEnd = MAX ( dim_date[date] )
RETURN
CALCULATE (
    [退款率],
    DATESBETWEEN ( dim_date[date], EOMONTH ( curEnd, -4 ) + 1, EOMONTH ( curEnd, -1 ) )
)

退款率偏离 pp = ( [退款率] - [退款率前 3 月基线] ) * 100

退款异常标记 =
IF (
    [退款率偏离 pp] >= 2.5
        && [退款率] >= [退款率前 3 月基线] * 1.18,
    "异常",
    "正常"
)
```

实现方式：矩阵视觉对象，行 = `dim_platform[platform]` + `dim_category[category]`，列 = `dim_date[year_month]`，值 = `[退款率偏离 pp]`；在"条件格式 → 背景色"中用规则（≥2.5 为红、≥5 为深红），再按 `[退款率偏离 pp]` 降序取前 6 行。

## 5. 页面布局（1440 × 1600 画布）

| 区域 | 视觉对象 | 字段 / 设置 |
| --- | --- | --- |
| 顶部标题 | 文本框 + 形状 | 深色底 `#0b1424`，标题"全渠道电商经营看板"；右侧放"合成数据"标签 |
| KPI 行（6 张卡片） | 卡片图 ×6 | 值：GMV / 订单量 / 客单价 / 支付转化率 / 退款率 / 48h 履约达成率；副标题放环比、同比 |
| 左上 | 折线图 | X=`dim_date[date]`，Y=`[GMV]`；加"7 日移动平均"度量值；用"参考线/形状"标出大促窗口 |
| 右上 | 矩阵或表 | 行=平台；值=GMV 占比、GMV、客单价、退款率、48h 履约达成率；GMV 占比列加数据条 |
| 中左 | 条形图 | Y=`dim_category[category]`，X=`[GMV]`，按 `[GMV]` 降序，开启数据标签（占比） |
| 中中 | 组合图（柱 + 线） | 柱=`[GMV]`（按渠道），线=`[渠道退款率]`，次坐标轴 |
| 中右 | 100% 堆积条形图 | Y=平台，图例=SLA 分桶，值=订单量占比；副标题放 48h 达成率 |
| 左下 | 矩阵 | 异常检测结果（见 4.5），按偏离降序 |
| 右下 | 文本框 / 卡片列表 | 5 条关键发现，内容来自 README |

主题色（"视图 → 主题 → 自定义"）：天猫 `#2F6BFF`、京东 `#0AA88F`、抖音 `#232936`、拼多多 `#DF6B3A`；正向好 `#0E9F6E`、负向/预警 `#D64545`。字体 Segoe UI / 微软雅黑，标题 13pt，正文 11pt。

交互：顶部放平台切片器（磁贴样式，单选/多选均可）；日期用"月份"切片器，默认选 `2025-08` 用于 KPI 区；开启"编辑交互"让异常矩阵不影响 KPI 卡片。

## 6. 校验清单（必须与脚本输出一致）

| 校验项 | 期望值 |
| --- | --- |
| 全周期 GMV | 13.18 亿元 |
| 全周期订单量 | 6,706,347 单 |
| 明细行数 | 73,080 行 |
| 京东 / 天猫 / 抖音 / 拼多多 GMV 占比 | 36.4% / 25.9% / 24.6% / 13.1% |
| 京东 / 天猫 / 抖音 / 拼多多 退款率 | 5.4% / 10.2% / 26.2% / 11.1% |
| 最新完整月（2025-08）GMV | 6,714 万元（环比 +12.3%，同比 +12.7%） |
| 最新完整月订单量 / 客单价 | 348,910 单 / ¥192 |
| 最新完整月退款率 / 48h 达成率 | 14.3% / 88.5% |
| 退款异常 Top1 | 2025-03 抖音·美妆个护，36.6%（基线 27.2%） |

若数字对不上，优先检查：日期列类型是否为日期、关系是否单向、是否误用了 `ALL` 而不是 `REMOVEFILTERS`、卡片是否被月份切片器筛选。

## 7. 刷新与发布

- 本地发布到"我的工作区"后，在"数据集设置"中配置 CSV 路径或改为导入模式；本作品集为静态数据，直接"导入"即可，无需网关。
- 若要保持可复现，请在发布说明中注明"数据由 `scripts/generate_data.py` 生成，种子 20260101"。
- Power BI 文件（.pbix）体积较大，建议单独放在 Release 附件而不是主仓库，本仓库只保留本说明与原始 CSV。
