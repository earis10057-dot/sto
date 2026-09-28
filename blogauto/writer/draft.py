"""주제 → 내 문체·섹션 구조에 맞춘 블로그 초안 + 제목/해시태그/요약/썸네일 문구."""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from ..config import resolve
from ..layout import THUMBNAIL, body_images
from ..llm import generate_json

DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "main_keyword": {"type": "string"},
        "titles": {"type": "array", "items": {"type": "string"}, "description": "제목 후보 5개"},
        "intro": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string", "description": "소제목 (기호 없이)"},
                    "quote": {"type": "string", "description": "섹션 핵심 한 줄 (인용구용, 40자 이내)"},
                    "body": {"type": "string", "description": "본문. 줄바꿈은 \\n, 목록은 '1. ' 또는 '- '"},
                    "card_caption": {"type": "string", "description": "섹션 이미지에 넣을 짧은 설명 (20자 이내)"},
                },
                "required": ["heading", "quote", "body", "card_caption"],
                "additionalProperties": False,
            },
        },
        "outro": {"type": "string"},
        "summary": {"type": "array", "items": {"type": "string"}, "description": "3줄 요약"},
        "hashtags": {"type": "array", "items": {"type": "string"}, "description": "# 없이 10~15개"},
        "thumbnail_texts": {
            "type": "array",
            "description": "썸네일 문구 3안. main 은 12자 내외 2줄 이내, 강조할 단어는 *별표*로 감싼다",
            "items": {
                "type": "object",
                "properties": {"main": {"type": "string"}, "sub": {"type": "string"}},
                "required": ["main", "sub"],
                "additionalProperties": False,
            },
        },
        "image_sections": {"type": "array", "items": {"type": "integer"},
                           "description": "본문 16:9 이미지를 넣을 소제목 번호(1부터) 2개. "
                                          "독자가 가장 궁금해할 핵심이나 조건·금액·절차를 정리한 소제목을 고르고, 서로 붙어 있지 않게"},
        "fact_check": {"type": "array", "items": {"type": "string"},
                       "description": "발행 전 공식 출처로 반드시 확인해야 할 사실(금액·기간·조건) 목록"},
    },
    "required": ["main_keyword", "titles", "intro", "sections", "outro", "summary", "hashtags",
                 "thumbnail_texts", "image_sections", "fact_check"],
    "additionalProperties": False,
}

SYSTEM = """당신은 네이버 블로그 글을 대신 써 주는 전문 작가입니다.
블로거 본인의 문체 가이드와 예전 글을 충실히 따라, 그 사람이 직접 쓴 것처럼 씁니다.

원칙:
- 참고자료에 있는 사실만 구체적으로 씁니다. 참고자료에 없는 금액·날짜·조건은 추측하지 말고 [확인 필요]로 표시한 뒤 fact_check 에 넣습니다.
- 메인 키워드는 제목과 도입부, 소제목 일부, 마무리에 자연스럽게 넣되 억지 반복은 피합니다.
- 과장광고·단정 표현(최고, 무조건, 100%, 누구나, 완치 등)은 쓰지 않습니다.
- 마크다운 문법(#, **, 표)은 쓰지 않습니다. 네이버 에디터에 그대로 붙여 넣을 평문으로 씁니다.
- 제목 후보는 25~35자, 숫자·대상·꼬리말(총정리, 신청방법 등)을 활용한 홈판 스타일로 5개 씁니다."""


def slugify(text: str) -> str:
    s = re.sub(r"[^\w가-힣]+", "-", text).strip("-")
    return s[:40] or "post"


def load_samples(samples_dir: Path, limit: int = 3) -> list[str]:
    if not samples_dir.exists():
        return []
    files = sorted(
        [p for p in samples_dir.iterdir() if p.suffix in {".txt", ".md"} and p.stem.lower() != "readme"],
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    return [p.read_text(encoding="utf-8") for p in files[:limit]]


def build_prompt(topic: str, keyword: str | None, notes: str, references: list[str],
                 style: str, samples: list[str], wcfg: dict[str, Any], today: date) -> str:
    parts = [f"오늘 날짜: {today.isoformat()}", f"## 주제\n{topic}"]
    if keyword:
        parts.append(f"## 메인 키워드\n{keyword}")
    parts.append(
        "## 형식\n"
        f"- 소제목 {wcfg.get('sections', 5)}개 (마무리 제외)\n"
        f"- 본문 전체 약 {wcfg.get('target_chars', 2500)}자 (공백 제외)\n"
        f"- 섹션 핵심 한 줄(quote)은 {'인용구로 강조되니 임팩트 있게' if wcfg.get('use_quote', True) else '짧게'} 씁니다."
    )
    parts.append(f"## 문체 가이드\n{style}")
    for i, s in enumerate(samples, 1):
        parts.append(f"## 내가 예전에 쓴 글 예시 {i} (말투·구성만 참고, 내용은 베끼지 말 것)\n{s}")
    if notes:
        parts.append(f"## 추가 요청\n{notes}")
    if references:
        parts.append("## 참고자료 (사실 정보는 여기서만 가져올 것)\n" + "\n\n---\n\n".join(references))
    else:
        parts.append("## 참고자료\n(없음 — 구체적 수치는 모두 [확인 필요]로 표시)")
    return "\n\n".join(parts)


def render(meta: dict[str, Any], wcfg: dict[str, Any], markdown: bool) -> str:
    """markdown=True 는 미리보기용(draft.md), False 는 네이버 에디터 붙여넣기용(draft.txt)."""
    mark = wcfg.get("heading_marker", "■")
    use_quote = wcfg.get("use_quote", True)
    plan = body_images(meta)
    image = lambda path, alt: f"![{alt}]({path})\n" if markdown else f"[이미지: {path}]\n"  # noqa: E731
    out: list[str] = []
    if markdown:
        out.append("<!-- 제목 후보 (하나를 골라 발행하세요) -->")
        out += [f"<!-- {i}. {t} -->" for i, t in enumerate(meta["titles"], 1)]
        out.append(f"\n# {meta['titles'][0]}\n")
        out.append(f"![썸네일]({THUMBNAIL})\n")
    else:
        out.append("[제목 후보]\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(meta["titles"], 1)))
        out.append("\n" + "=" * 30 + "\n")
        out.append(f"[대표 이미지(썸네일): {THUMBNAIL}]\n")
    out.append(meta["intro"].strip() + "\n")
    out.append(image(plan["contents"], "목차"))

    for i, sec in enumerate(meta["sections"], 1):
        if i in plan["sections"]:
            out.append(image(plan["sections"][i], f"소제목 {i}"))
        out.append(f"{'## ' if markdown else ''}{mark} {sec['heading']}\n")
        if use_quote and sec["quote"].strip():
            out.append(f"> {sec['quote']}\n" if markdown else f"[인용구] {sec['quote']}\n")
        out.append(sec["body"].strip() + "\n")

    out.append(image(plan["summary"], "요약"))
    out.append(f"{'## ' if markdown else ''}{mark} 한눈에 정리\n")
    out += [f"✔ {s}" for s in meta["summary"]]
    out.append("\n" + meta["outro"].strip() + "\n")
    out.append(" ".join(f"#{h.lstrip('#').replace(' ', '')}" for h in meta["hashtags"]))
    return "\n".join(out) + "\n"


def save(meta: dict[str, Any], post_dir: Path, wcfg: dict[str, Any]) -> None:
    post_dir.mkdir(parents=True, exist_ok=True)
    (post_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (post_dir / "draft.md").write_text(render(meta, wcfg, markdown=True), encoding="utf-8")
    (post_dir / "draft.txt").write_text(render(meta, wcfg, markdown=False), encoding="utf-8")


def load_meta(post_dir: Path) -> dict[str, Any]:
    path = post_dir / "meta.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} 가 없습니다. write 명령으로 만든 폴더를 지정하세요.")
    return json.loads(path.read_text(encoding="utf-8"))


def body_text(meta: dict[str, Any]) -> str:
    """점검용 본문 전체(제목 제외)."""
    parts = [meta["intro"]]
    for s in meta["sections"]:
        parts += [s["heading"], s["quote"], s["body"]]
    parts += meta["summary"] + [meta["outro"]]
    return "\n".join(parts)


def run(settings: dict[str, Any], topic: str, keyword: str | None = None, notes: str = "",
        ref_files: list[str] | None = None, today: date | None = None,
        ref_texts: list[str] | None = None) -> tuple[Path, dict[str, Any]]:
    today = today or date.today()
    wcfg = settings.get("writer", {})
    style_path = resolve(wcfg.get("style_file", "config/style.md"))
    style = style_path.read_text(encoding="utf-8") if style_path.exists() else ""
    samples = load_samples(resolve(wcfg.get("samples_dir", "config/samples")))
    references = [Path(f).read_text(encoding="utf-8") for f in (ref_files or [])]
    references += [t for t in (ref_texts or []) if t.strip()]

    prompt = build_prompt(topic, keyword, notes, references, style, samples, wcfg, today)
    meta = generate_json(SYSTEM, prompt, DRAFT_SCHEMA, effort="high")
    meta["topic"] = topic
    meta["created"] = today.isoformat()
    if keyword:
        meta["main_keyword"] = keyword

    post_dir = resolve(wcfg.get("output_dir", "output/posts")) / f"{today:%Y%m%d}_{slugify(keyword or topic)}"
    save(meta, post_dir, wcfg)
    return post_dir, meta
