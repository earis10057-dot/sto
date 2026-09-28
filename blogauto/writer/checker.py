"""맞춤법(선택, Claude) + 금칙어·과장광고 + 키워드·분량 점검."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..llm import generate_json


@dataclass
class Finding:
    category: str
    word: str
    context: str
    reason: str
    suggestion: str


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    spelling: list[dict[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings and not self.warnings


def load_rules(path: Path) -> dict[str, dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _context(text: str, start: int, end: int, pad: int = 18) -> str:
    s = text[max(0, start - pad): end + pad].replace("\n", " ")
    return ("…" if start > pad else "") + s + ("…" if end + pad < len(text) else "")


def find_banned(text: str, rules: dict[str, dict[str, Any]]) -> list[Finding]:
    out: list[Finding] = []
    seen: set[tuple[str, int]] = set()
    for cat, rule in rules.items():
        patterns = [re.escape(w) for w in rule.get("words", [])] + list(rule.get("patterns", []))
        for pat in patterns:
            for m in re.finditer(pat, text):
                if (m.group(0), m.start()) in seen:
                    continue
                seen.add((m.group(0), m.start()))
                out.append(Finding(cat, m.group(0), _context(text, m.start(), m.end()),
                                   rule.get("reason", ""), rule.get("suggestion", "")))
    return out


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?。])\s+|\n+", text) if s.strip()]


def check_structure(meta: dict[str, Any], body: str, ccfg: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    chars = len(re.sub(r"\s", "", body))
    kw = (meta.get("main_keyword") or "").strip()
    kw_count = body.count(kw) if kw else 0
    kw_nospace = body.replace(" ", "").count(kw.replace(" ", "")) if kw else 0
    long_limit = ccfg.get("long_sentence", 120)
    long_sents = [s for s in _sentences(body) if len(s) > long_limit]
    titles_with_kw = sum(1 for t in meta.get("titles", []) if kw and kw.replace(" ", "") in t.replace(" ", ""))

    stats = {
        "본문 글자수(공백 제외)": chars,
        "메인 키워드": kw or "-",
        "키워드 등장 횟수": kw_count,
        "키워드 등장 횟수(띄어쓰기 무시)": kw_nospace,
        "키워드 포함 제목 후보": f"{titles_with_kw}/{len(meta.get('titles', []))}",
        "소제목 수": len(meta.get("sections", [])),
        "해시태그 수": len(meta.get("hashtags", [])),
        "긴 문장 수": len(long_sents),
    }
    if chars < ccfg.get("min_chars", 1500):
        warnings.append(f"본문이 {chars}자로 짧아요 (권장 {ccfg.get('min_chars', 1500)}자 이상).")
    if kw and kw_nospace < ccfg.get("keyword_min", 3):
        warnings.append(f"메인 키워드 '{kw}'가 {kw_nospace}번만 나와요 (권장 {ccfg.get('keyword_min', 3)}회 이상).")
    if kw and kw_nospace > ccfg.get("keyword_max", 12):
        warnings.append(f"메인 키워드 '{kw}'가 {kw_nospace}번 반복돼요. 과도한 반복은 어뷰징으로 보일 수 있어요.")
    if kw and titles_with_kw == 0:
        warnings.append("제목 후보 중 메인 키워드가 들어간 제목이 없어요.")
    for s in long_sents[:5]:
        warnings.append(f"문장이 너무 길어요({len(s)}자): {s[:50]}…")
    if "[확인 필요]" in body:
        warnings.append(f"[확인 필요] 표시가 {body.count('[확인 필요]')}곳 있어요. 공식 출처로 확인 후 고쳐 주세요.")
    return stats, warnings


SPELL_SCHEMA = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "original": {"type": "string", "description": "본문에 있는 그대로의 틀린 부분 (앞뒤 몇 글자 포함)"},
                    "suggestion": {"type": "string", "description": "original 을 고친 문자열"},
                    "type": {"type": "string", "enum": ["맞춤법", "띄어쓰기", "문법", "어색한 표현"]},
                    "reason": {"type": "string"},
                },
                "required": ["original", "suggestion", "type", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["issues"],
    "additionalProperties": False,
}

SPELL_SYSTEM = (
    "당신은 한국어 교정 전문가입니다. 국립국어원 표준 맞춤법·띄어쓰기 기준으로 블로그 글을 교정합니다. "
    "블로그 특유의 구어체 말투(~거든요, ~더라고요)는 틀린 것이 아니므로 고치지 않습니다. "
    "확실한 오류만 지적하고, original 은 본문에서 그대로 찾을 수 있는 문자열이어야 합니다."
)


def spell_check(text: str) -> list[dict[str, str]]:
    res = generate_json(SPELL_SYSTEM, f"다음 글을 교정해 주세요.\n\n{text}", SPELL_SCHEMA,
                        effort="medium", max_tokens=16000)
    return [i for i in res["issues"] if i["original"] and i["original"] != i["suggestion"]]


def apply_spelling(meta: dict[str, Any], issues: list[dict[str, str]]) -> int:
    """meta 의 본문 필드에 교정 결과를 반영한다. 반영한 건수를 반환."""
    applied = 0

    def fix(s: str) -> str:
        nonlocal applied
        for i in issues:
            if i["original"] in s:
                s = s.replace(i["original"], i["suggestion"])
                applied += 1
        return s

    meta["intro"] = fix(meta["intro"])
    meta["outro"] = fix(meta["outro"])
    meta["summary"] = [fix(s) for s in meta["summary"]]
    for sec in meta["sections"]:
        for k in ("heading", "quote", "body"):
            sec[k] = fix(sec[k])
    return applied


def run_check(meta: dict[str, Any], body: str, rules: dict[str, dict[str, Any]], ccfg: dict[str, Any],
              spelling: bool = False) -> Report:
    rep = Report()
    title_text = "\n".join(meta.get("titles", []))
    rep.findings = find_banned(title_text + "\n" + body, rules)
    rep.stats, rep.warnings = check_structure(meta, body, ccfg)
    if spelling:
        rep.spelling = spell_check(body)
    return rep


def report_markdown(rep: Report) -> str:
    md = ["# 발행 전 점검 리포트\n", "## 기본 지표\n", "| 항목 | 값 |", "|---|---|"]
    md += [f"| {k} | {v} |" for k, v in rep.stats.items()]
    md.append("\n## 경고\n")
    md += [f"- ⚠️ {w}" for w in rep.warnings] or ["- 없음 ✅"]
    md.append("\n## 금칙어·과장광고 표현\n")
    if rep.findings:
        md += ["| 분류 | 표현 | 문맥 | 이유 | 바꿔 쓰기 |", "|---|---|---|---|---|"]
        md += [f"| {f.category} | **{f.word}** | {f.context} | {f.reason} | {f.suggestion} |" for f in rep.findings]
    else:
        md.append("- 발견된 표현 없음 ✅")
    md.append("\n## 맞춤법·띄어쓰기\n")
    if rep.spelling:
        md += ["| 유형 | 원문 | 수정안 | 이유 |", "|---|---|---|---|"]
        md += [f"| {s['type']} | {s['original']} | {s['suggestion']} | {s['reason']} |" for s in rep.spelling]
    else:
        md.append("- 검사하지 않았거나 발견된 오류 없음 (`--spell` 옵션으로 검사)")
    return "\n".join(md) + "\n"
