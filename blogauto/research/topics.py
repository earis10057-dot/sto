"""홈판·인기글 제목 패턴을 분석해 '오늘 쓸 주제 후보'를 뽑는다."""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from ..config import require_env, resolve
from ..llm import generate_json
from . import keywords as kw_mod
from .naver_api import NaverOpenAPI

# 제목 끝에 자주 붙는 '후킹 꼬리말'
HOOK_ENDINGS = ["총정리", "방법", "신청", "조건", "대상", "정리", "후기", "꿀팁", "비교", "차이", "기간", "금액", "주의", "변경", "확인"]
STOPWORDS = {"그리고", "하는", "있는", "이번", "지금", "모든", "정말", "우리", "여러분", "대한", "위한", "관련"}
PARTICLE_RE = re.compile(r"(은|는|이|가|을|를|의|에|에서|으로|로|와|과|도|만|까지|부터)$")


def load_homefeed(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()]
    return [ln for ln in lines if ln and not ln.startswith("#")]


def _tokens(title: str) -> list[str]:
    words = re.findall(r"[가-힣A-Za-z0-9]+", title)
    out = []
    for w in words:
        w = PARTICLE_RE.sub("", w) if len(w) > 2 else w
        if len(w) >= 2 and w not in STOPWORDS and not w.isdigit():
            out.append(w)
    return out


def analyze_titles(titles: list[str]) -> dict[str, Any]:
    """제목 목록의 형식적 특징을 수치로 요약한다."""
    n = len(titles)
    if n == 0:
        return {"count": 0}
    pct = lambda cond: round(sum(1 for t in titles if cond(t)) / n * 100)  # noqa: E731
    tokens = Counter(tok for t in titles for tok in set(_tokens(t)))
    endings = Counter(e for t in titles for e in HOOK_ENDINGS if e in t)
    return {
        "count": n,
        "avg_length": round(sum(len(t) for t in titles) / n, 1),
        "with_number_pct": pct(lambda t: bool(re.search(r"\d", t))),
        "with_year_pct": pct(lambda t: bool(re.search(r"20\d\d", t))),
        "question_pct": pct(lambda t: "?" in t),
        "bracket_pct": pct(lambda t: bool(re.search(r"[\[\(【〔]", t))),
        "exclaim_pct": pct(lambda t: "!" in t),
        "top_words": tokens.most_common(25),
        "top_endings": endings.most_common(10),
    }


def pattern_markdown(stats: dict[str, Any], label: str) -> str:
    if not stats.get("count"):
        return f"### {label}\n\n(데이터 없음)\n"
    words = ", ".join(f"{w}({c})" for w, c in stats["top_words"])
    ends = ", ".join(f"{w}({c})" for w, c in stats["top_endings"]) or "-"
    return (
        f"### {label} — {stats['count']}개 제목\n\n"
        f"| 항목 | 값 |\n|---|---|\n"
        f"| 평균 길이 | {stats['avg_length']}자 |\n"
        f"| 숫자 포함 | {stats['with_number_pct']}% |\n"
        f"| 연도 포함 | {stats['with_year_pct']}% |\n"
        f"| 물음표 | {stats['question_pct']}% |\n"
        f"| 괄호/대괄호 | {stats['bracket_pct']}% |\n"
        f"| 느낌표 | {stats['exclaim_pct']}% |\n\n"
        f"**자주 나온 단어**: {words}\n\n**자주 쓴 꼬리말**: {ends}\n"
    )


TOPIC_SCHEMA = {
    "type": "object",
    "properties": {
        "trend_summary": {"type": "string", "description": "지금 밀어주는 주제·제목 패턴 요약 3~5문장"},
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "main_keyword": {"type": "string"},
                    "why_now": {"type": "string", "description": "지금 써야 하는 이유(데이터 근거)"},
                    "angle": {"type": "string", "description": "다른 글과 차별화할 관점"},
                    "title_examples": {"type": "array", "items": {"type": "string"}},
                    "priority": {"type": "string", "enum": ["상", "중", "하"]},
                },
                "required": ["topic", "main_keyword", "why_now", "angle", "title_examples", "priority"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["trend_summary", "candidates"],
    "additionalProperties": False,
}

SYSTEM = (
    "당신은 네이버 생활정보 블로그 전문 콘텐츠 기획자입니다. "
    "주어진 홈판·인기글 제목, 검색량, 트렌드 데이터에만 근거해 오늘 쓸 주제를 제안합니다. "
    "데이터에 없는 사실(금액, 날짜, 정책 내용)을 지어내지 마세요. "
    "제목 예시는 네이버 홈판 스타일(구체적 숫자, 대상 명시, 꼬리말)로 25~35자 안팎으로 씁니다. "
    "과장·낚시성 표현('무조건', '100%', '충격')은 쓰지 않습니다."
)


def build_prompt(homefeed: list[str], searched: dict[str, list[str]], volumes: list[dict], rising: list[dict],
                 home_stats: dict, search_stats: dict, count: int, today: date) -> str:
    parts = [f"오늘 날짜: {today.isoformat()}", f"주제 후보 {count}개를 우선순위 순으로 제안해 주세요.\n"]
    parts.append("## 홈판·인기글 제목 (사용자가 수집)\n" + ("\n".join(f"- {t}" for t in homefeed[:150]) or "(없음)"))
    parts.append("## 홈판 제목 패턴 통계\n" + json.dumps(home_stats, ensure_ascii=False))
    for seed, titles in searched.items():
        parts.append(f"## '{seed}' 네이버 블로그 상위 글 제목\n" + "\n".join(f"- {t}" for t in titles[:30]))
    if searched:
        parts.append("## 상위 글 제목 패턴 통계\n" + json.dumps(search_stats, ensure_ascii=False))
    if volumes:
        parts.append("## 월간 검색량 상위 키워드 (PC+모바일)\n" + "\n".join(
            f"- {v['키워드']}: {v['합계']} (경쟁 {v['경쟁정도']})" for v in volumes))
    if rising:
        parts.append("## 최근 검색 트렌드 급상승 (최근 평균 vs 이전 평균)\n" + "\n".join(
            f"- {r['키워드']}: {r['변화율(%)']}%" for r in rising[:20]))
    return "\n\n".join(parts)


def run(settings: dict[str, Any], homefeed_file: str | None = None, use_llm: bool = True,
        use_search: bool = True, today: date | None = None, api: NaverOpenAPI | None = None) -> dict[str, Any]:
    today = today or date.today()
    tcfg = settings.get("topics", {})
    homefeed = load_homefeed(resolve(homefeed_file or tcfg.get("homefeed_file", "data/homefeed.txt")))

    searched: dict[str, list[str]] = {}
    if use_search:
        if api is None:
            cid, csec = require_env("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET")
            api = NaverOpenAPI(cid, csec)
        for seed in settings.get("seed_keywords", []):
            items = api.search_blog(seed, display=tcfg.get("search_display", 30))
            searched[seed] = [it["title"] for it in items]

    home_stats = analyze_titles(homefeed)
    search_stats = analyze_titles([t for ts in searched.values() for t in ts])
    volumes = kw_mod.latest_volumes(settings)
    rising = kw_mod.latest_rising(settings)

    md = [f"# 오늘의 주제 후보 — {today.isoformat()}\n", "## 제목 패턴 분석\n",
          pattern_markdown(home_stats, "홈판·인기글"), pattern_markdown(search_stats, "시드 키워드 상위 블로그 글")]

    result: dict[str, Any] = {"date": today.isoformat(), "home_stats": home_stats, "search_stats": search_stats}
    if use_llm:
        if not (homefeed or searched or volumes):
            raise ValueError("분석할 데이터가 없습니다. data/homefeed.txt 에 제목을 넣거나 keywords 수집을 먼저 실행하세요.")
        count = tcfg.get("count", 10)
        prompt = build_prompt(homefeed, searched, volumes, rising, home_stats, search_stats, count, today)
        ideas = generate_json(SYSTEM, prompt, TOPIC_SCHEMA, effort="medium", max_tokens=16000)
        result.update(ideas)
        md.append("## 트렌드 요약\n\n" + ideas["trend_summary"] + "\n")
        md.append("## 주제 후보\n")
        for i, c in enumerate(ideas["candidates"], 1):
            titles = "\n".join(f"  - {t}" for t in c["title_examples"])
            md.append(
                f"### {i}. {c['topic']}  `[{c['priority']}]`\n\n"
                f"- **메인 키워드**: {c['main_keyword']}\n- **왜 지금**: {c['why_now']}\n"
                f"- **차별화 관점**: {c['angle']}\n- **제목 예시**\n{titles}\n\n"
                f"  ▶ 초안 작성: `python -m blogauto write \"{c['topic']}\" --keyword \"{c['main_keyword']}\"`\n"
            )

    out_dir = resolve(tcfg.get("output_dir", "output/topics"))
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{today.isoformat()}.md"
    md_path.write_text("\n".join(md), encoding="utf-8")
    (out_dir / f"{today.isoformat()}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["path"] = md_path
    return result
