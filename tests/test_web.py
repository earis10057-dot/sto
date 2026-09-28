"""웹 조사 기능 테스트. Claude 는 가짜 클라이언트로 대신한다."""
import json
from datetime import date
from types import SimpleNamespace as NS

import pytest

from blogauto import cli, llm, pipeline
from blogauto.research import web
from blogauto.writer import draft


class FakeStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.message


class FakeClient:
    """stream() 이 부를 때마다 준비된 응답을 순서대로 돌려준다."""

    def __init__(self, messages):
        self.messages = list(messages)
        self.calls = []
        self.beta = NS(messages=NS(stream=self._stream))

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        return FakeStream(self.messages.pop(0))


def _search_result(*pairs):
    return NS(type="web_search_tool_result",
              content=[NS(type="web_search_result", url=u, title=t) for u, t in pairs])


def test_web_research_resumes_pause_turn_and_collects_sources():
    first = NS(stop_reason="pause_turn", content=[
        NS(type="server_tool_use", name="web_search"),
        _search_result(("https://www.gov.kr/a", "정부24 안내"), ("https://news.example/b", "뉴스")),
    ])
    second = NS(stop_reason="end_turn", content=[
        NS(type="web_fetch_tool_result",
           content=NS(type="web_fetch_result", url="https://www.nts.go.kr/c", content=NS(title="국세청 공지"))),
        NS(type="web_search_tool_result", content=NS(type="web_search_tool_result_error", error_code="max_uses_exceeded")),
        NS(type="text", text="신청은 9월 1일부터예요.",
           citations=[NS(url="https://www.nts.go.kr/c", title="국세청 공지")]),
        NS(type="text", text=" 대상은 근로소득자예요.", citations=None),
    ])
    client = FakeClient([first, second])
    text, sources = llm.web_research("sys", "prompt", client_factory=lambda: client)

    assert text == "신청은 9월 1일부터예요. 대상은 근로소득자예요."
    assert [s["url"] for s in sources] == ["https://www.nts.go.kr/c", "https://www.gov.kr/a", "https://news.example/b"]
    # 두 번째 요청은 첫 응답을 assistant 로 붙여 그대로 이어서 보낸다 ("계속" 같은 말을 덧붙이지 않음)
    assert client.calls[1]["messages"][-1] == {"role": "assistant", "content": first.content}
    tools = client.calls[0]["tools"]
    assert {t["type"] for t in tools} == {"web_search_20260209", "web_fetch_20260209"}


def test_web_research_errors():
    refuse = NS(stop_reason="refusal", content=[])
    with pytest.raises(llm.LLMError):
        llm.web_research("s", "p", client_factory=lambda: FakeClient([refuse]))
    paused = [NS(stop_reason="pause_turn", content=[]) for _ in range(llm.MAX_CONTINUATIONS + 1)]
    with pytest.raises(llm.LLMError, match="오래"):
        llm.web_research("s", "p", client_factory=lambda: FakeClient(paused))


HOT = {"trend_summary": "지원금 신청 시즌", "candidates": [
    {"topic": "B 주제", "main_keyword": "B", "why_now": "보통", "angle": "b", "title_examples": ["b"], "priority": "중"},
    {"topic": "A 주제", "main_keyword": "A", "why_now": "9/1 신청 시작 (정부24)", "angle": "실수 사례",
     "title_examples": ["a"], "priority": "상"},
]}
SOURCES = [{"url": "https://www.gov.kr/a", "title": "정부24 안내"}, {"url": "https://news.example/b", "title": "뉴스"}]


def test_find_hot_topics_and_pick(settings, project, monkeypatch):
    seen = {}
    monkeypatch.setattr(web, "web_research", lambda system, prompt, **kw: (seen.setdefault("p", prompt), ("노트", SOURCES))[1])
    monkeypatch.setattr(web, "generate_json", lambda system, prompt, schema, **kw: (seen.setdefault("j", prompt), HOT)[1])
    res = web.find_hot_topics(settings, today=date(2026, 9, 28))
    assert "정부지원금·복지" in seen["p"] and "2026-09-28" in seen["p"]
    assert "https://www.gov.kr/a" in seen["j"]
    md = res["path"].read_text(encoding="utf-8")
    assert "A 주제" in md and "정부24 안내" in md
    assert json.loads((project / "output/topics/2026-09-28_web.json").read_text(encoding="utf-8"))["sources"] == SOURCES
    assert web.pick_topic(res)["topic"] == "A 주제"  # 우선순위 '상' 이 먼저
    with pytest.raises(ValueError):
        web.pick_topic({"candidates": []})


def test_write_post_with_web_references(settings, project, sample_meta, monkeypatch):
    prompts = []
    monkeypatch.setattr(web, "web_research", lambda *a, **k: ("대상: 근로소득자 (출처 gov.kr, 2026-09-01 기준)", SOURCES))
    monkeypatch.setattr(draft, "generate_json", lambda s, prompt, schema, **k: (prompts.append(prompt),
                        {k2: v for k2, v in sample_meta.items() if k2 != "topic"})[1])
    post_dir = pipeline.write_post(settings, "근로장려금 신청", keyword="근로장려금", web=True)

    assert "대상: 근로소득자" in prompts[0] and "https://www.gov.kr/a" in prompts[0]
    txt = (post_dir / "draft.txt").read_text(encoding="utf-8")
    assert "📌 참고 출처" in txt and "- 정부24 안내: https://www.gov.kr/a" in txt
    assert txt.index("📌 참고 출처") < txt.index("#근로장려금")
    assert "[정부24 안내](https://www.gov.kr/a)" in (post_dir / "draft.md").read_text(encoding="utf-8")
    assert "대상: 근로소득자" in (post_dir / "research.md").read_text(encoding="utf-8")
    assert json.loads((post_dir / "meta.json").read_text(encoding="utf-8"))["sources"] == SOURCES
    assert len(list((post_dir / "images").glob("*.png"))) == 5


def test_write_post_without_web_has_no_sources(settings, project, sample_meta, monkeypatch):
    monkeypatch.setattr(web, "web_research", lambda *a, **k: pytest.fail("웹 조사를 하면 안 됨"))
    monkeypatch.setattr(draft, "generate_json", lambda *a, **k: {k2: v for k2, v in sample_meta.items() if k2 != "topic"})
    post_dir = pipeline.write_post(settings, "근로장려금 신청", images=False)
    assert "참고 출처" not in (post_dir / "draft.txt").read_text(encoding="utf-8")
    assert not (post_dir / "research.md").exists()


def test_cli_auto(settings, project, sample_meta, monkeypatch, capsys):
    monkeypatch.setattr(web, "web_research", lambda *a, **k: ("노트", SOURCES))
    monkeypatch.setattr(web, "generate_json", lambda *a, **k: HOT)
    monkeypatch.setattr(draft, "generate_json", lambda *a, **k: {k2: v for k2, v in sample_meta.items() if k2 != "topic"})
    assert cli.main(["auto", "--no-images"]) == 0
    out = capsys.readouterr().out
    assert "고른 주제: A 주제" in out and "출처 2곳" in out
    post_dir = next((project / "output" / "posts").iterdir())
    assert json.loads((post_dir / "meta.json").read_text(encoding="utf-8"))["topic"] == "A 주제"


def test_low_credit_error_is_explained_in_korean():
    import anthropic
    import httpx2 as httpx

    def handler(req):
        return httpx.Response(400, json={"type": "error", "error": {
            "type": "invalid_request_error",
            "message": "Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing."}})

    client = anthropic.Anthropic(api_key="x", max_retries=0,
                                 http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(llm.LLMError, match="크레딧이 부족"):
        llm.web_research("s", "p", client_factory=lambda: client)
