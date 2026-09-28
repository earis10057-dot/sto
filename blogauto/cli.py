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


def cmd_write(args, settings):
    from .pipeline import write_post
    write_post(settings, args.topic, keyword=args.keyword, notes=args.notes or "", ref_files=args.ref,
               web=args.web, spell=args.spell, apply=args.apply_spelling, images=not args.no_images, theme=args.theme)


def cmd_hot(args, settings):
    from .research import web
    res = web.find_hot_topics(settings)
    print(f"✅ 요즘 뜨는 주제 리포트 → {res['path']}")
    for i, c in enumerate(res["candidates"], 1):
        print(f"   {i:>2}. [{c['priority']}] {c['topic']}  (키워드: {c['main_keyword']})")
    print('   ▶ 글쓰기: python -m blogauto write "주제" -k 키워드 --web')


def cmd_auto(args, settings):
    from .pipeline import auto_post
    auto_post(settings, spell=args.spell, apply=args.apply_spelling, images=not args.no_images, theme=args.theme)


def cmd_check(args, settings):
    from .pipeline import check_and_report
    check_and_report(Path(args.post_dir), settings, spell=args.spell, apply=args.apply_spelling)


def cmd_images(args, settings):
    from .pipeline import render_images
    render_images(Path(args.post_dir), settings, args.theme, args.thumb)


def _post_options(s: argparse.ArgumentParser) -> None:
    s.add_argument("--spell", action="store_true", help="AI 맞춤법 검사 포함")
    s.add_argument("--apply-spelling", action="store_true", help="맞춤법 수정안을 초안에 바로 반영")
    s.add_argument("--no-images", action="store_true")
    s.add_argument("--theme", help="이미지 테마: navy|mint|coral|mono|forest")


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
    s.add_argument("--web", "-w", action="store_true", help="웹에서 공식 자료·뉴스를 검색해 참고자료로 사용")
    _post_options(s)
    s.set_defaults(func=cmd_write)

    s = sub.add_parser("hot", help="웹 검색으로 요즘 뜨는 생활정보 주제 찾기 (네이버 키 불필요)")
    s.set_defaults(func=cmd_hot)

    s = sub.add_parser("auto", help="알아서 쓰기: 뜨는 주제 찾기 → 웹 조사 → 초안 + 점검 + 이미지")
    _post_options(s)
    s.set_defaults(func=cmd_auto)

    s = sub.add_parser("check", help="초안 폴더 다시 점검")
    s.add_argument("post_dir"); s.add_argument("--spell", action="store_true")
    s.add_argument("--apply-spelling", action="store_true")
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("images", help="초안 폴더의 meta.json 으로 이미지 다시 만들기")
    s.add_argument("post_dir"); s.add_argument("--theme")
    s.add_argument("--thumb", type=int, default=1, help="썸네일 문구 후보 중 몇 번째를 쓸지 (1~3)")
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
