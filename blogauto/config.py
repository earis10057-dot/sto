"""설정(.env + config/settings.yaml) 로딩."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(os.getenv("BLOGAUTO_ROOT", Path(__file__).resolve().parent.parent))
SETTINGS_FILE = ROOT / "config" / "settings.yaml"

load_dotenv(ROOT / ".env")


class ConfigError(RuntimeError):
    pass


def load_settings(path: Path | None = None) -> dict[str, Any]:
    path = path or SETTINGS_FILE
    if not path.exists():
        raise ConfigError(f"설정 파일이 없습니다: {path}")
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve(p: str | Path) -> Path:
    """설정 파일 속 상대 경로를 프로젝트 루트 기준 절대 경로로 바꾼다."""
    p = Path(p)
    return p if p.is_absolute() else ROOT / p


def require_env(*names: str) -> list[str]:
    values = [os.getenv(n, "").strip() for n in names]
    missing = [n for n, v in zip(names, values) if not v]
    if missing:
        raise ConfigError(
            f"환경변수 {', '.join(missing)} 가(이) 비어 있습니다. "
            ".env.example 을 .env 로 복사한 뒤 값을 채워 주세요."
        )
    return values
