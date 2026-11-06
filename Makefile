PY ?= python

.PHONY: help setup all data metrics build test lint format clean

help:
	@echo "setup   安装依赖（运行时 + 开发）"
	@echo "all     生成数据 → 计算指标 → 构建看板"
	@echo "data    仅重新生成 data/*.csv"
	@echo "metrics 仅重算 data/metrics.json"
	@echo "build   仅重建 dashboard/index.html"
	@echo "test    运行单元测试"
	@echo "lint    ruff 检查 + 格式校验"
	@echo "format  自动修复 lint 并格式化"

setup:
	$(PY) -m pip install -r requirements-dev.txt

all:
	$(PY) -m ecommerce_kpi all

data:
	$(PY) -m ecommerce_kpi generate

metrics:
	$(PY) -m ecommerce_kpi metrics

build:
	$(PY) -m ecommerce_kpi render

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

format:
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

clean:
	$(PY) -m pytest --cache-clear >/dev/null 2>&1 || true
	@echo "构建产物与数据由 git 跟踪，未删除；仅清理缓存"
