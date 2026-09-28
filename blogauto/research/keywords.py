"""검색량(검색광고 API)과 트렌드(데이터랩)를 매일 수집해 스프레드시트에 쌓는다."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from ..config import require_env, resolve
from .naver_api import NaverOpenAPI, NaverSearchAd
from .sheet import read_rows, replace_sheet, upsert_rows

VOLUME_SHEET = "검색량"
VOLUME_HEADER = ["수집일", "시드", "키워드", "PC", "모바일", "합계", "경쟁정도", "평균노출광고수"]
TREND_SHEET = "트렌드"
TREND_HEADER = ["키워드", "날짜", "비율"]
RISING_SHEET = "급상승"
RISING_HEADER = ["기준일", "키워드", "최근평균", "이전평균", "변화율(%)"]


def _chunks(items: list[str], n: int):
    for i in range(0, len(items), n):
        yield items[i : i + n]


def collect_volumes(ad: NaverSearchAd, seeds: list[str], limit: int, min_total: int) -> list[dict[str, Any]]:
    """시드별 연관 키워드를 검색량 순으로 limit 개까지."""
    out = []
    for seed in seeds:
        rows = [r for r in ad.keyword_tool([seed]) if r["total"] >= min_total]
        rows.sort(key=lambda r: r["total"], reverse=True)
        out.extend({"seed": seed, **r} for r in rows[:limit])
    return out


def collect_trends(api: NaverOpenAPI, keywords: list[str], days: int, today: date) -> dict[str, list[tuple[str, float]]]:
    """키워드별 일간 트렌드. 키워드마다 따로 조회해 각자 0~100 스케일로 받는다."""
    end = today - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    result: dict[str, list[tuple[str, float]]] = {}
    for kw in keywords:
        # 5개씩 묶으면 서로의 상대값으로 정규화되어 작은 키워드가 0에 뭉개지므로 하나씩 조회
        res = api.datalab_search(start, end, [(kw, [kw])])
        for group in res:
            result[group["title"]] = [(d["period"], float(d["ratio"])) for d in group.get("data", [])]
    return result


def rising_keywords(trends: dict[str, list[tuple[str, float]]], window: int) -> list[tuple[str, float, float, float]]:
    """최근 window 일 평균 vs 직전 window 일 평균. 변화율 큰 순."""
    out = []
    for kw, series in trends.items():
        vals = [v for _, v in sorted(series)]
        if len(vals) < window * 2:
            continue
        recent = sum(vals[-window:]) / window
        prev = sum(vals[-2 * window : -window]) / window
        change = (recent - prev) / prev * 100 if prev else (100.0 if recent else 0.0)
        out.append((kw, round(recent, 2), round(prev, 2), round(change, 1)))
    out.sort(key=lambda r: r[3], reverse=True)
    return out


def run(settings: dict[str, Any], seeds: list[str] | None = None, today: date | None = None,
        ad: NaverSearchAd | None = None, api: NaverOpenAPI | None = None) -> dict[str, Any]:
    today = today or date.today()
    seeds = seeds or settings.get("seed_keywords", [])
    if not seeds:
        raise ValueError("settings.yaml 의 seed_keywords 가 비어 있습니다.")
    kcfg = settings.get("keywords", {})
    tcfg = settings.get("trend", {})
    path = resolve(kcfg.get("spreadsheet", "data/keywords.xlsx"))

    if ad is None:
        key, secret, cid = require_env("NAVER_AD_API_KEY", "NAVER_AD_SECRET_KEY", "NAVER_AD_CUSTOMER_ID")
        ad = NaverSearchAd(key, secret, cid)
    if api is None:
        cid, csec = require_env("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET")
        api = NaverOpenAPI(cid, csec)

    today_s = today.isoformat()
    volumes = collect_volumes(ad, seeds, kcfg.get("related_limit", 30), kcfg.get("min_monthly_total", 100))
    upsert_rows(
        path, VOLUME_SHEET, VOLUME_HEADER,
        ([today_s, v["seed"], v["keyword"], v["pc"], v["mobile"], v["total"], v["comp_idx"], v["ad_depth"]] for v in volumes),
        replace_if=lambda r: str(r[0]) == today_s,
    )

    trends = collect_trends(api, seeds, tcfg.get("days", 30), today)
    trend_keys = {(kw, p) for kw, s in trends.items() for p, _ in s}
    upsert_rows(
        path, TREND_SHEET, TREND_HEADER,
        ([kw, p, r] for kw, s in trends.items() for p, r in s),
        replace_if=lambda r: (r[0], str(r[1])) in trend_keys,
    )

    rising = rising_keywords(trends, tcfg.get("rising_window", 7))
    replace_sheet(path, RISING_SHEET, RISING_HEADER, ([today_s, *r] for r in rising))
    return {"path": path, "volumes": volumes, "rising": rising}


def latest_volumes(settings: dict[str, Any], top: int = 30) -> list[dict[str, Any]]:
    """스프레드시트에서 가장 최근 수집일의 검색량 상위 키워드."""
    path = resolve(settings.get("keywords", {}).get("spreadsheet", "data/keywords.xlsx"))
    rows = read_rows(path, VOLUME_SHEET)
    if not rows:
        return []
    last = max(str(r["수집일"]) for r in rows)
    rows = [r for r in rows if str(r["수집일"]) == last]
    rows.sort(key=lambda r: r["합계"] or 0, reverse=True)
    return rows[:top]


def latest_rising(settings: dict[str, Any]) -> list[dict[str, Any]]:
    path = resolve(settings.get("keywords", {}).get("spreadsheet", "data/keywords.xlsx"))
    return read_rows(path, RISING_SHEET)
