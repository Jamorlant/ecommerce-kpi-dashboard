"""构建测试：占位符被替换、产物可独立打开的前提是数据已内联。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from ecommerce_kpi.config import Settings
from ecommerce_kpi.errors import DataContractError
from ecommerce_kpi.render import render_dashboard


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        seed=1,
        start=date(2024, 1, 1),
        end=date(2024, 2, 1),
        data_dir=tmp_path / "data",
        dashboard_dir=tmp_path / "dashboard",
        log_level="INFO",
    )


def _prepare(tmp_path: Path, template: str) -> Settings:
    settings = _settings(tmp_path)
    settings.data_dir.mkdir(parents=True)
    (settings.dashboard_dir / "vendor").mkdir(parents=True)
    (settings.data_dir / "metrics.json").write_text(json.dumps({"meta": {"rows": 3}}), encoding="utf-8")
    (settings.dashboard_dir / "vendor" / "echarts.min.js").write_text("/* echarts stub */", encoding="utf-8")
    (settings.dashboard_dir / "template.html").write_text(template, encoding="utf-8")
    return settings


def test_render_inlines_data_and_library(tmp_path: Path) -> None:
    settings = _prepare(
        tmp_path,
        "<html><script>__ECHARTS__</script><script>window.DATA=__DATA_JSON__;</script></html>",
    )

    render_dashboard(settings)
    html = (settings.dashboard_dir / "index.html").read_text(encoding="utf-8")

    assert "__ECHARTS__" not in html
    assert "__DATA_JSON__" not in html
    assert "/* echarts stub */" in html
    assert '"rows":3' in html


def test_missing_placeholder_fails_loudly(tmp_path: Path) -> None:
    settings = _prepare(tmp_path, "<html>no placeholder here</html>")

    with pytest.raises(DataContractError, match="缺少占位符"):
        render_dashboard(settings)


def test_missing_metrics_file_points_to_next_step(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    (settings.dashboard_dir / "vendor").mkdir(parents=True)
    (settings.dashboard_dir / "template.html").write_text("__DATA_JSON__ __ECHARTS__", encoding="utf-8")
    (settings.dashboard_dir / "vendor" / "echarts.min.js").write_text("", encoding="utf-8")

    with pytest.raises(DataContractError, match="metrics"):
        render_dashboard(settings)
