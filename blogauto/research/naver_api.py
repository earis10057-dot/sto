"""네이버 오픈API(데이터랩·검색)와 검색광고 API 클라이언트."""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import re
import time
from datetime import date
from typing import Any

import requests

TIMEOUT = 20


class NaverAPIError(RuntimeError):
    pass


def _check(resp: requests.Response, name: str) -> Any:
    if resp.status_code != 200:
        raise NaverAPIError(f"{name} 호출 실패 ({resp.status_code}): {resp.text[:300]}")
    return resp.json()


def strip_tags(text: str) -> str:
    """검색 API 결과의 <b> 태그와 HTML 엔티티를 제거한다."""
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


class NaverOpenAPI:
    """developers.naver.com 에서 발급한 Client ID/Secret 으로 호출하는 API."""

    BASE = "https://openapi.naver.com"

    def __init__(self, client_id: str, client_secret: str, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.headers = {
            "X-Naver-Client-Id": client_id,
            "X-Naver-Client-Secret": client_secret,
        }

    def datalab_search(
        self,
        start: date,
        end: date,
        groups: list[tuple[str, list[str]]],
        time_unit: str = "date",
    ) -> list[dict[str, Any]]:
        """검색어 트렌드. groups 는 최대 5개 (그룹명, [검색어...]).

        반환: [{"title": 그룹명, "data": [{"period": "2026-09-01", "ratio": 12.3}, ...]}]
        ratio 는 요청한 그룹들 중 최대값을 100으로 한 상대값이다.
        """
        if not 1 <= len(groups) <= 5:
            raise ValueError("데이터랩은 한 번에 1~5개 그룹만 조회할 수 있습니다.")
        body = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "timeUnit": time_unit,
            "keywordGroups": [{"groupName": g, "keywords": kws[:20]} for g, kws in groups],
        }
        resp = self.session.post(
            f"{self.BASE}/v1/datalab/search", json=body, headers=self.headers, timeout=TIMEOUT
        )
        return _check(resp, "데이터랩 검색어 트렌드").get("results", [])

    def search_blog(self, query: str, display: int = 30, sort: str = "sim") -> list[dict[str, Any]]:
        """블로그 검색. sort: sim(정확도) | date(최신)."""
        resp = self.session.get(
            f"{self.BASE}/v1/search/blog.json",
            params={"query": query, "display": min(display, 100), "sort": sort},
            headers=self.headers,
            timeout=TIMEOUT,
        )
        items = _check(resp, "블로그 검색").get("items", [])
        for it in items:
            it["title"] = strip_tags(it.get("title", ""))
            it["description"] = strip_tags(it.get("description", ""))
        return items


def _to_int(v: Any) -> int:
    """검색광고 API 는 검색량이 적으면 '< 10' 문자열을 준다. 이 경우 5로 본다."""
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).replace(",", "").strip()
    if s.startswith("<"):
        return 5
    try:
        return int(float(s))
    except ValueError:
        return 0


class NaverSearchAd:
    """searchad.naver.com > 도구 > API 사용 관리 에서 발급한 키로 호출하는 API."""

    BASE = "https://api.searchad.naver.com"

    def __init__(self, api_key: str, secret_key: str, customer_id: str, session: requests.Session | None = None):
        self.api_key = api_key
        self.secret_key = secret_key
        self.customer_id = customer_id
        self.session = session or requests.Session()

    @staticmethod
    def signature(secret_key: str, timestamp: str, method: str, uri: str) -> str:
        msg = f"{timestamp}.{method}.{uri}"
        digest = hmac.new(secret_key.encode(), msg.encode(), hashlib.sha256).digest()
        return base64.b64encode(digest).decode()

    def _headers(self, method: str, uri: str) -> dict[str, str]:
        ts = str(int(time.time() * 1000))
        return {
            "X-Timestamp": ts,
            "X-API-KEY": self.api_key,
            "X-Customer": str(self.customer_id),
            "X-Signature": self.signature(self.secret_key, ts, method, uri),
        }

    def keyword_tool(self, hints: list[str]) -> list[dict[str, Any]]:
        """연관 키워드와 월간 검색량. hints 는 최대 5개, 공백은 자동 제거.

        반환 항목: keyword, pc, mobile, total, comp_idx, ad_depth
        """
        hints = [h.replace(" ", "") for h in hints if h.strip()][:5]
        if not hints:
            return []
        uri = "/keywordstool"
        resp = self.session.get(
            f"{self.BASE}{uri}",
            params={"hintKeywords": ",".join(hints), "showDetail": 1},
            headers=self._headers("GET", uri),
            timeout=TIMEOUT,
        )
        rows = []
        for k in _check(resp, "검색광고 키워드 도구").get("keywordList", []):
            pc = _to_int(k.get("monthlyPcQcCnt"))
            mo = _to_int(k.get("monthlyMobileQcCnt"))
            rows.append(
                {
                    "keyword": k.get("relKeyword", ""),
                    "pc": pc,
                    "mobile": mo,
                    "total": pc + mo,
                    "comp_idx": k.get("compIdx", ""),
                    "ad_depth": k.get("plAvgDepth", 0),
                }
            )
        return rows
