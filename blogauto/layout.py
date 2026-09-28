"""글 한 편의 이미지 구성과 본문 속 위치.

- 썸네일 1장 (1:1)
- 본문 이미지 4장 (16:9)
  1) 도입부 다음: 목차 카드
  2) 3) 핵심 소제목 2곳: 소제목 카드
  4) 마무리 '한눈에 정리' 위: 요약 카드
"""
from __future__ import annotations

from typing import Any

THUMBNAIL = "images/thumbnail.png"
THUMB_SIZE = (1080, 1080)
BODY_SIZE = (1280, 720)


def image_sections(meta: dict[str, Any]) -> list[int]:
    """소제목 카드를 넣을 소제목 번호(1부터) 2개.

    초안 작성 때 AI가 고른 image_sections 를 쓰고, 없거나 잘못됐으면 소제목 사이에 고르게 배치한다.
    """
    n = len(meta.get("sections", []))
    if n == 0:
        return []
    picked = sorted({i for i in meta.get("image_sections", []) if isinstance(i, int) and 1 <= i <= n})
    if len(picked) == min(2, n):
        return picked
    return sorted({max(1, min(n, round((n + 1) * k / 3))) for k in (1, 2)})


def body_images(meta: dict[str, Any]) -> dict[str, Any]:
    """본문 이미지 파일 경로를 등장 순서대로 번호 매겨 돌려준다.

    반환: {"contents": 경로, "sections": {소제목번호: 경로}, "summary": 경로}
    """
    counter = iter(range(1, 100))
    name = lambda: f"images/body_{next(counter):02d}.png"  # noqa: E731
    plan: dict[str, Any] = {"contents": name(), "sections": {}}
    for i in image_sections(meta):
        plan["sections"][i] = name()
    plan["summary"] = name()
    return plan
