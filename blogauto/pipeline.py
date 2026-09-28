"""글 한 편을 만드는 전체 흐름: (웹 조사) → 초안 → 점검 → 이미지.

명령어(cli.py)와 버튼 프로그램(gui.py)이 같은 함수를 쓴다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import resolve

MAX_SOURCES_IN_POST = 8  # 글 끝 '참고 출처'에 넣을 최대 개수


def check_and_report(post_dir: Path, settings: dict[str, Any], spell: bool = False, apply: bool = False) -> Path:
    from .writer import checker, draft
    meta = draft.load_meta(post_dir)
    ccfg = settings.get("checker", {})
    rules = checker.load_rules(resolve(ccfg.get("banned_words_file", "config/banned_words.yaml")))
    rep = checker.run_check(meta, draft.body_text(meta), rules, ccfg, spelling=spell or apply)
    if apply and rep.spelling:
        n = checker.apply_spelling(meta, rep.spelling)
        draft.save(meta, post_dir, settings.get("writer", {}))
        print(f"✏️  맞춤법 수정 {n}건을 초안에 반영했습니다.")
    path = post_dir / "check_report.md"
    path.write_text(checker.report_markdown(rep), encoding="utf-8")
    print(f"🔎 점검: 금칙어 {len(rep.findings)}건 · 경고 {len(rep.warnings)}건 · 맞춤법 {len(rep.spelling)}건 → {path}")
    for f in rep.findings[:10]:
        print(f"   - [{f.category}] '{f.word}' : {f.context}")
    for w in rep.warnings:
        print(f"   - ⚠️ {w}")
    return post_dir


def render_images(post_dir: Path, settings: dict[str, Any], theme: str | None = None, thumb: int = 1) -> Path:
    from .images.cards import render_post
    from .writer.draft import load_meta
    paths = render_post(load_meta(post_dir), post_dir, settings.get("images", {}), theme, thumb=thumb)
    print(f"🖼️  썸네일 1장(1:1) + 본문 이미지 {len(paths) - 1}장(16:9) 생성 → {post_dir / 'images'}")
    print("   본문 속 위치는 draft.txt 의 [이미지: ...] 표시를 참고하세요.")
    return post_dir


def write_post(settings: dict[str, Any], topic: str, keyword: str | None = None, notes: str = "",
               ref_files: list[str] | None = None, ref_texts: list[str] | None = None, web: bool = False,
               spell: bool = False, apply: bool = False, images: bool = True, theme: str | None = None) -> Path:
    """주제 하나로 글 폴더를 만든다. web=True 면 먼저 웹에서 참고자료를 조사한다."""
    from .research import web as web_mod
    from .writer import draft

    ref_texts = list(ref_texts or [])
    research: tuple[str, list[dict[str, str]]] | None = None
    if web:
        print("🌐 웹에서 참고자료 조사 중... (공식 사이트·뉴스 검색, 2~5분 걸릴 수 있어요)")
        research = web_mod.gather_references(settings, topic, keyword)
        ref_texts.append(web_mod.reference_text(*research))
        print(f"   출처 {len(research[1])}곳을 확인했어요.")

    print("✍️  초안 작성 중... (1~3분 걸릴 수 있어요)")
    post_dir, meta = draft.run(settings, topic, keyword=keyword, notes=notes, ref_files=ref_files,
                               ref_texts=ref_texts)
    if research:
        meta["sources"] = research[1][:MAX_SOURCES_IN_POST]
        draft.save(meta, post_dir, settings.get("writer", {}))
        web_mod.save_research(post_dir, *research)
    print(f"✅ 초안 저장 → {post_dir}")
    print("   제목 후보:")
    for i, t in enumerate(meta["titles"], 1):
        print(f"     {i}. {t}")
    print("   해시태그: " + " ".join(f"#{h}" for h in meta["hashtags"]))

    check_and_report(post_dir, settings, spell=spell, apply=apply)
    if images:
        render_images(post_dir, settings, theme)
    if meta.get("fact_check"):
        print("📌 발행 전 공식 출처로 확인할 것:")
        for f in meta["fact_check"]:
            print(f"   - {f}")
    return post_dir


def auto_post(settings: dict[str, Any], spell: bool = False, apply: bool = False, images: bool = True,
              theme: str | None = None) -> Path:
    """주제 찾기부터 끝까지: 요즘 뜨는 주제 검색 → 가장 우선순위 높은 주제 → 웹 조사 → 글."""
    from .research import web as web_mod
    print("🔥 웹에서 요즘 뜨는 주제를 찾는 중... (2~5분 걸릴 수 있어요)")
    res = web_mod.find_hot_topics(settings)
    pick = web_mod.pick_topic(res)
    print(f"👉 고른 주제: {pick['topic']} (키워드: {pick['main_keyword']})")
    print(f"   이유: {pick['why_now']}")
    return write_post(settings, pick["topic"], keyword=pick["main_keyword"], notes=f"관점: {pick['angle']}",
                      web=True, spell=spell, apply=apply, images=images, theme=theme)
