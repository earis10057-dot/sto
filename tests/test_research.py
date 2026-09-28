import base64
import hashlib
import hmac
from datetime import date

from blogauto.research import keywords, monitor, topics
from blogauto.research.naver_api import NaverOpenAPI, NaverSearchAd, strip_tags
from blogauto.research.sheet import read_rows

from .conftest import FakeResponse, FakeSession


def test_searchad_signature_matches_hmac_sha256():
    expected = base64.b64encode(hmac.new(b"secret", b"1700000000000.GET./keywordstool", hashlib.sha256).digest()).decode()
    assert NaverSearchAd.signature("secret", "1700000000000", "GET", "/keywordstool") == expected


def test_keyword_tool_parses_counts_and_strips_spaces():
    payload = {"keywordList": [
        {"relKeyword": "근로장려금", "monthlyPcQcCnt": 12000, "monthlyMobileQcCnt": 88000, "compIdx": "중간", "plAvgDepth": 15},
        {"relKeyword": "근로장려금반기", "monthlyPcQcCnt": "< 10", "monthlyMobileQcCnt": "1,200", "compIdx": "낮음"},
    ]}
    s = FakeSession({"keywordstool": FakeResponse(payload=payload)})
    rows = NaverSearchAd("k", "s", "1", session=s).keyword_tool(["주택담보대출 금리"])
    assert s.calls[0][2]["params"]["hintKeywords"] == "주택담보대출금리"
    assert {"X-Signature", "X-API-KEY", "X-Customer", "X-Timestamp"} <= set(s.calls[0][2]["headers"])
    assert rows[0]["total"] == 100000
    assert rows[1] == {"keyword": "근로장려금반기", "pc": 5, "mobile": 1200, "total": 1205, "comp_idx": "낮음", "ad_depth": 0}


def test_search_blog_strips_tags():
    assert strip_tags("<b>근로장려금</b> &amp; 자녀장려금") == "근로장려금 & 자녀장려금"
    s = FakeSession({"search/blog": FakeResponse(payload={"items": [{"title": "<b>청년</b>도약계좌", "description": ""}]})})
    assert NaverOpenAPI("i", "s", session=s).search_blog("청년도약계좌")[0]["title"] == "청년도약계좌"


def _series(values, start_day=1):
    return [{"period": f"2026-09-{d:02d}", "ratio": v} for d, v in enumerate(values, start_day)]


def test_keywords_run_writes_spreadsheet_idempotently(settings, project):
    ad_payload = {"keywordList": [
        {"relKeyword": "A", "monthlyPcQcCnt": 50, "monthlyMobileQcCnt": 60},
        {"relKeyword": "B", "monthlyPcQcCnt": 1000, "monthlyMobileQcCnt": 9000},
        {"relKeyword": "C", "monthlyPcQcCnt": "< 10", "monthlyMobileQcCnt": "< 10"},  # min_total 미만 → 제외
    ]}

    def datalab(kw):
        name = kw["json"]["keywordGroups"][0]["groupName"]
        vals = [10] * 7 + [20] * 7 if name == "근로장려금" else [10] * 14
        return FakeResponse(payload={"results": [{"title": name, "data": _series(vals)}]})

    ad = NaverSearchAd("k", "s", "1", session=FakeSession({"keywordstool": FakeResponse(payload=ad_payload)}))
    api = NaverOpenAPI("i", "s", session=FakeSession({"datalab": datalab}))
    settings["seed_keywords"] = ["근로장려금", "기초연금"]
    settings["trend"]["days"] = 14

    for _ in range(2):  # 같은 날 두 번 실행해도 중복 없음
        res = keywords.run(settings, today=date(2026, 9, 15), ad=ad, api=api)

    vol = read_rows(res["path"], "검색량")
    assert len(vol) == 4 and vol[0]["키워드"] == "B"
    assert len(read_rows(res["path"], "트렌드")) == 28
    rising = read_rows(res["path"], "급상승")
    assert rising[0]["키워드"] == "근로장려금" and rising[0]["변화율(%)"] == 100.0
    assert keywords.latest_volumes(settings)[0]["키워드"] == "B"


def test_analyze_titles():
    stats = topics.analyze_titles([
        "2026 근로장려금 신청방법 총정리",
        "청년도약계좌 해지하면 손해일까?",
        "[필독] 기초연금 수급 조건 총정리",
    ])
    assert stats["count"] == 3
    assert stats["with_year_pct"] == 33 and stats["question_pct"] == 33 and stats["bracket_pct"] == 33
    assert ("총정리", 2) in stats["top_endings"]


def test_topics_run_with_llm(settings, project, monkeypatch):
    (project / "data" / "homefeed.txt").write_text("# 주석\n2026 근로장려금 총정리\n기초연금 인상 소식\n", encoding="utf-8")
    captured = {}

    def fake_llm(system, prompt, schema, **kw):
        captured["prompt"] = prompt
        return {"trend_summary": "지원금 주제 강세", "candidates": [{
            "topic": "근로장려금 반기 신청", "main_keyword": "근로장려금 반기", "why_now": "9월 신청기간",
            "angle": "실수 사례", "title_examples": ["근로장려금 반기 신청 총정리"], "priority": "상"}]}

    monkeypatch.setattr(topics, "generate_json", fake_llm)
    res = topics.run(settings, use_search=False, today=date(2026, 9, 28))
    assert "2026 근로장려금 총정리" in captured["prompt"] and "# 주석" not in captured["prompt"]
    md = res["path"].read_text(encoding="utf-8")
    assert "근로장려금 반기 신청" in md and "python -m blogauto write" in md


RSS = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>t</title>{items}</channel></rss>"""
ITEM = "<item><title>{t}</title><link>https://www.korea.kr/{i}</link><guid>{i}</guid></item>"


def test_monitor_first_run_records_then_notifies_new_matching(settings, project, monkeypatch):
    settings["monitor"]["sources"] = [{"name": "테스트", "type": "rss", "url": "https://x/rss"}]
    sent = []
    monkeypatch.setattr(monitor.notify, "send", lambda text: sent.append(text))

    items = [ITEM.format(t="기존 지원금 안내", i=1)]
    sess = FakeSession({"x/rss": lambda kw: FakeResponse(content=RSS.format(items="".join(items)).encode())})
    assert monitor.run(settings, session=sess)["new"] == []  # 첫 실행은 기록만

    items += [ITEM.format(t="청년 월세 지원금 신청 시작", i=2), ITEM.format(t="공무원 채용 공고", i=3),
              ITEM.format(t="장관 동정", i=4)]
    res = monitor.run(settings, session=sess)
    assert [it["title"] for it in res["new"]] == ["청년 월세 지원금 신청 시작"]
    assert sent and "청년 월세 지원금" in sent[0]
    assert monitor.run(settings, session=sess)["new"] == []  # 이미 본 글은 다시 알리지 않음


def test_monitor_html_source(settings, project, monkeypatch):
    html = '<table><td class="subject"><a href="/view?id=7">소상공인 대출 금리 인하</a></td></table>'
    settings["monitor"]["sources"] = [{"name": "게시판", "type": "html", "url": "https://gov.example/list",
                                        "link_selector": "td.subject a"}]
    sess = FakeSession({"gov.example": FakeResponse(content=html.encode(), text=html)})
    res = monitor.run(settings, session=sess, dry_run=True, notify_initial=True)
    assert res["new"][0]["link"] == "https://gov.example/view?id=7"
