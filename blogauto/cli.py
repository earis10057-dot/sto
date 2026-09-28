"""명령줄 진입점: python -m blogauto <명령>"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import ConfigError, load_settings, resolve
from .llm import LLMError
from .research.naver_api import NaverAPIError


def cmd_keywords(args, settings):
    from .research import keywords
    seeds = [s.strip() for s in args.seeds.split(",")] if args.seeds else None
    res = keywords.run(settings, seeds=seeds)
    print(f"✅ 연관 키워드 {len(res['volumes'])}개 저장 → {res['path']}")
    if res["rising"]:
        print("📈 트렌드 변화 (최근 vs 이전):")
        for kw, recent, prev, change in res["rising"][:10]:
            print(f"   {kw:<20} {change:+.1f}%  ({prev} → {recent})")


def cmd_topics(args, settings):
    from .research import topics
    res = topics.run(settings, homefeed_file=args.homefeed, use_llm=not args.no_llm, use_search=not args.no_search)
    print(f"✅ 주제 후보 리포트 → {res['path']}")
    for i, c in enumerate(res.get("candidates", []), 1):
        print(f"   {i:>2}. [{c['priority']}] {c['topic']}  (키워드: {c['main_keyword']})")


def cmd_monitor(args, settings):
    from .research import monitor
    res = monitor.run(settings, dry_run=args.dry_run, notify_initial=args.notify_initial)
    if not res["new"]:
        print("새로 올라온 관련 공고가 없습니다. (처음 실행이면 현재 글 목록만 기록합니다)")


def cmd_daily(args, settings):
    for name, fn in (("키워드 수집", cmd_keywords), ("주제 후보", cmd_topics), ("공고 모니터링", cmd_monitor)):
        print(f"\n━━ {name} ━━")
        try:
            fn(args, settings)
        except (ConfigError, NaverAPIError, LLMError, ValueError) as e:
            print(f"⚠️  {name} 건너뜀: {e}")


def _check_and_report(post_dir: Path, settings, spell: bool, apply: bool):
    from .writer import checker, draft
    meta = draft.load_meta(post_dir)
    ccfg = settings.get("checker", {})
    rules = checker.load_rules(resolve(ccfg.get("banned_words_file", "config/banned_words.yaml")))
    rep = checker.run_check(meta, draft.body_text(meta), rules, ccfg, spelling=spell)
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


def _images(post_dir: Path, settings, theme):
    from .images.cards import render_post
    from .writer.draft import load_meta
    paths = render_post(load_meta(post_dir), post_dir, settings.get("images", {}), theme)
    print(f"🖼️  이미지 {len(paths)}장 생성 → {post_dir / 'images'}")


def cmd_write(args, settings):
    from .writer import draft
    print("✍️  초안 작성 중... (1~3분 걸릴 수 있어요)")
    post_dir, meta = draft.run(settings, args.topic, keyword=args.keyword, notes=args.notes or "", ref_files=args.ref)
    print(f"✅ 초안 저장 → {post_dir}")
    print("   제목 후보:")
    for i, t in enumerate(meta["titles"], 1):
        print(f"     {i}. {t}")
    print("   해시태그: " + " ".join(f"#{h}" for h in meta["hashtags"]))
    _check_and_report(post_dir, settings, spell=args.spell, apply=args.apply_spelling)
    if not args.no_images:
        _images(post_dir, settings, args.theme)
    if meta.get("fact_check"):
        print("📌 발행 전 공식 출처로 확인할 것:")
        for f in meta["fact_check"]:
            print(f"   - {f}")


def cmd_check(args, settings):
    _check_and_report(Path(args.post_dir), settings, spell=args.spell, apply=args.apply_spelling)


def cmd_images(args, settings):
    _images(Path(args.post_dir), settings, args.theme)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="blogauto", description="네이버 블로그 리서치·초안·이미지 자동화")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("keywords", help="검색량·트렌드 수집 → data/keywords.xlsx")
    s.add_argument("--seeds", help="쉼표로 구분한 시드 키워드 (기본: settings.yaml)")
    s.set_defaults(func=cmd_keywords)

    s = sub.add_parser("topics", help="홈판·인기글 패턴 분석 → 오늘의 주제 후보")
    s.add_argument("--homefeed", help="홈판 제목 파일 (기본: data/homefeed.txt)")
    s.add_argument("--no-llm", action="store_true", help="AI 없이 패턴 통계만")
    s.add_argument("--no-search", action="store_true", help="네이버 블로그 검색 생략")
    s.set_defaults(func=cmd_topics)

    s = sub.add_parser("monitor", help="정부·공공 사이트 새 공고 감시 → 알림")
    s.add_argument("--dry-run", action="store_true", help="기록·알림 없이 결과만 출력")
    s.add_argument("--notify-initial", action="store_true", help="처음 실행 때도 기존 글을 알림")
    s.set_defaults(func=cmd_monitor)

    s = sub.add_parser("daily", help="keywords + topics + monitor 한 번에 (예약 실행용)")
    s.add_argument("--seeds"); s.add_argument("--homefeed")
    s.set_defaults(func=cmd_daily, no_llm=False, no_search=False, dry_run=False, notify_initial=False)

    s = sub.add_parser("write", help="주제 → 초안 + 제목/태그/요약 + 점검 + 이미지")
    s.add_argument("topic", help="글 주제")
    s.add_argument("--keyword", "-k", help="메인 키워드")
    s.add_argument("--notes", "-n", help="추가 요청 (예: '신청 방법을 단계별로 자세히')")
    s.add_argument("--ref", "-r", action="append", help="참고자료 텍스트 파일 (공고 원문 등, 여러 번 지정 가능)")
    s.add_argument("--spell", action="store_true", help="AI 맞춤법 검사 포함")
    s.add_argument("--apply-spelling", action="store_true", help="맞춤법 수정안을 초안에 바로 반영")
    s.add_argument("--no-images", action="store_true")
    s.add_argument("--theme", help="이미지 테마: navy|mint|coral|mono|forest")
    s.set_defaults(func=cmd_write)

    s = sub.add_parser("check", help="초안 폴더 다시 점검")
    s.add_argument("post_dir"); s.add_argument("--spell", action="store_true")
    s.add_argument("--apply-spelling", action="store_true")
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("images", help="초안 폴더의 meta.json 으로 이미지 다시 만들기")
    s.add_argument("post_dir"); s.add_argument("--theme")
    s.set_defaults(func=cmd_images)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args, load_settings())
    except (ConfigError, NaverAPIError, LLMError, FileNotFoundError, ValueError) as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
    return 0
