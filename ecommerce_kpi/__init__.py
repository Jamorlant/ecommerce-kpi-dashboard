"""电商 KPI 看板的可复现分析流水线。

对外只暴露一个入口：``python -m ecommerce_kpi <generate|metrics|render|all>``。
所有业务参数集中在 scenario.py（建模假设），运行参数集中在 config.py（环境变量）。
"""

__version__ = "1.0.0"
