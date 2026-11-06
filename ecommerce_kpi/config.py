"""运行参数解析：环境变量优先，其次 .env，最后是仓库默认值。

为什么把种子/周期/路径外置：作品集的读者最常做的一件事是"换一段周期重跑看看"，
硬编码在脚本顶部会让人改代码；而周期一改，README 里的数字就会失真，
所以能力保留、默认值不变，并在 .env.example 里写清楚代价。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ecommerce_kpi.errors import KpiError

ROOT = Path(__file__).resolve().parents[1]

_ALLOWED_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


@dataclass(frozen=True, slots=True)
class Settings:
    seed: int
    start: date
    end: date
    data_dir: Path
    dashboard_dir: Path
    log_level: str


def load_dotenv(env_file: Path) -> None:
    """把 .env 载入 os.environ；已存在的环境变量优先（便于 CI/一次性覆盖）。

    只支持 KEY=VALUE 与 # 注释，够用即可，不为一个 20 行的需求引入额外依赖。
    """
    if not env_file.exists():
        return
    for line_no, raw in enumerate(env_file.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if not key:
            raise KpiError(f"{env_file.name} 第 {line_no} 行缺少键名")
        os.environ.setdefault(key, value)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise KpiError(f"{name} 需要整数，实际为 {raw!r}") from exc


def _env_date(name: str, default: date) -> date:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise KpiError(f"{name} 需要 YYYY-MM-DD，实际为 {raw!r}") from exc


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    path = Path(raw)
    return path if path.is_absolute() else (ROOT / path)


def load_settings(env_file: Path | None = None) -> Settings:
    """读取配置并做一次集中校验，避免错误在下游以难懂的形式暴露。"""
    load_dotenv(env_file if env_file is not None else ROOT / ".env")

    settings = Settings(
        seed=_env_int("KPI_SEED", 20260101),
        start=_env_date("KPI_START_DATE", date(2024, 1, 1)),
        end=_env_date("KPI_END_DATE", date(2025, 8, 31)),
        data_dir=_env_path("KPI_DATA_DIR", ROOT / "data"),
        dashboard_dir=_env_path("KPI_DASHBOARD_DIR", ROOT / "dashboard"),
        log_level=os.environ.get("KPI_LOG_LEVEL", "INFO").upper(),
    )

    if settings.start > settings.end:
        raise KpiError(f"KPI_START_DATE({settings.start}) 晚于 KPI_END_DATE({settings.end})")
    if settings.log_level not in _ALLOWED_LOG_LEVELS:
        raise KpiError(f"KPI_LOG_LEVEL 只能是 {sorted(_ALLOWED_LOG_LEVELS)}，实际为 {settings.log_level}")
    return settings
