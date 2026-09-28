"""한글 폰트 자동 탐색."""
from __future__ import annotations

import os
from pathlib import Path

from ..config import ROOT

# (굵게, 보통) 순서로 운영체제별 흔한 한글 폰트 경로
CANDIDATES_BOLD = [
    "C:/Windows/Fonts/malgunbd.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/Library/Fonts/NanumGothicBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]
CANDIDATES_REGULAR = [
    "C:/Windows/Fonts/malgun.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/Library/Fonts/NanumGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]


def _from_fonts_dir(bold: bool) -> Path | None:
    """프로젝트 fonts/ 폴더에 넣어 둔 폰트를 우선 사용. 파일명에 Bold/ExtraBold/Heavy 가 있으면 굵은 폰트로 본다."""
    d = ROOT / "fonts"
    if not d.exists():
        return None
    files = sorted(p for p in d.iterdir() if p.suffix.lower() in {".ttf", ".otf", ".ttc"})
    is_bold = lambda p: any(k in p.stem.lower() for k in ("bold", "heavy", "black"))  # noqa: E731
    pick = [p for p in files if is_bold(p) == bold] or files
    return pick[0] if pick else None


def find_font(bold: bool, override: str = "") -> str:
    env = os.getenv("BLOGAUTO_FONT_BOLD" if bold else "BLOGAUTO_FONT", "")
    for p in (override, env):
        if p and Path(p).exists():
            return p
    local = _from_fonts_dir(bold)
    if local:
        return str(local)
    for p in CANDIDATES_BOLD if bold else CANDIDATES_REGULAR:
        if Path(p).exists():
            return p
    raise FileNotFoundError(
        "한글 폰트를 찾지 못했습니다. 나눔고딕·프리텐다드 등 .ttf/.otf 파일을 프로젝트의 fonts/ 폴더에 넣거나 "
        "settings.yaml 의 images.font_bold / font_regular 에 경로를 지정하세요."
    )
