## 这个改动解决什么问题

<!-- 一句话说明动机；如果是口径变化，请写清楚受影响的指标 -->

## 改动范围

- [ ] 数据生成（`ecommerce_kpi/generate.py` / `scenario.py`）
- [ ] 指标口径（`ecommerce_kpi/metrics.py` / `pipeline.py`）
- [ ] 看板前端（`dashboard/template.html`）
- [ ] 工程化（CI / 测试 / 依赖）
- [ ] 文档（README / docs）

## 口径影响

<!-- 是否改变任何指标的分子/分母？如果改变，README 与 docs/powerbi、docs/finebi 是否同步？ -->

- [ ] 未改变指标口径
- [ ] 改变口径，且已同步 README、Power BI / FineBI 复刻文档

## 验证方式

- [ ] `pytest` 通过
- [ ] `ruff check . && ruff format --check .` 通过
- [ ] `python -m ecommerce_kpi all` 重建成功
- [ ] 数据可复现（`git diff --exit-code data/` 无差异，或已说明为何变化）
- [ ] 双击 `dashboard/index.html` 可离线打开，筛选联动正常

## 截图 / 数据

<!-- 涉及视觉或结论变化时附截图，并贴出新旧关键数字 -->
