"""설정(.env + config/settings.yaml + config/user.yaml) 로딩과 저장."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(os.getenv("BLOGAUTO_ROOT", Path(__file__).resolve().parent.parent))

load_dotenv(ROOT / ".env")


class ConfigError(RuntimeError):
    pass


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def user_settings_path() -> Path:
    return ROOT / "config" / "user.yaml"


def load_settings(path: Path | None = None) -> dict[str, Any]:
    """settings.yaml 에 화면(프로그램)에서 바꾼 값(user.yaml)을 덮어써서 돌려준다."""
    path = path or ROOT / "config" / "settings.yaml"
    if not path.exists():
        raise ConfigError(f"설정 파일이 없습니다: {path}")
    with path.open(encoding="utf-8") as f:
        settings = yaml.safe_load(f) or {}
    user = path.parent / "user.yaml"
    if user.exists():
        with user.open(encoding="utf-8") as f:
            settings = _deep_merge(settings, yaml.safe_load(f) or {})
    return settings


def save_user_settings(updates: dict[str, Any]) -> None:
    """화면에서 바꾼 설정을 config/user.yaml 에 저장한다 (settings.yaml 의 설명 주석은 그대로 둔다)."""
    path = user_settings_path()
    current: dict[str, Any] = {}
    if path.exists():
        current = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    merged = _deep_merge(current, updates)
    path.write_text(yaml.safe_dump(merged, allow_unicode=True, sort_keys=False), encoding="utf-8")


def save_env(updates: dict[str, str]) -> None:
    """.env 의 해당 키만 바꾸고 나머지 줄(주석 포함)은 유지한다. 바로 적용되도록 환경변수도 갱신."""
    path = ROOT / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(updates)
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if not line.lstrip().startswith("#") and "=" in line and key in remaining:
            lines[i] = f"{key}={remaining.pop(key)}"
    lines += [f"{k}={v}" for k, v in remaining.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for k, v in updates.items():
        os.environ[k] = v


def resolve(p: str | Path) -> Path:
    """설정 파일 속 상대 경로를 프로젝트 루트 기준 절대 경로로 바꾼다."""
    p = Path(p)
    return p if p.is_absolute() else ROOT / p


def require_env(*names: str) -> list[str]:
    values = [os.getenv(n, "").strip() for n in names]
    missing = [n for n, v in zip(names, values) if not v]
    if missing:
        raise ConfigError(
            f"{', '.join(missing)} 가(이) 비어 있습니다. "
            "프로그램의 '설정' 탭에서 입력하거나 .env 파일에 값을 채워 주세요."
        )
    return values
