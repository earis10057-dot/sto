"""Claude 호출 공통 모듈.

- generate_json: JSON 스키마로 구조화된 응답을 받는다.
- web_research: 웹 검색·웹 페이지 열람 도구로 조사한 결과(글 + 출처 목록)를 받는다.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable

import anthropic

DEFAULT_MODEL = "claude-opus-5"
# 안전 분류기가 요청을 거절하면 서버가 다른 모델로 자동 재시도하도록 하는 옵션
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# 웹 검색이 서버에서 오래 걸려 중간에 멈추면(pause_turn) 이어서 요청하는 최대 횟수
MAX_CONTINUATIONS = 5


class LLMError(RuntimeError):
    pass


def model_name() -> str:
    return os.getenv("BLOGAUTO_MODEL", DEFAULT_MODEL)


def _model_kwargs() -> dict[str, Any]:
    model = model_name()
    kwargs: dict[str, Any] = {"model": model}
    if model.startswith(("claude-opus-5", "claude-fable-5")):
        kwargs.update(betas=[FALLBACK_BETA], fallbacks="default")
    return kwargs


def _stream(client: anthropic.Anthropic, **kwargs: Any):
    """스트리밍으로 요청하고 완성된 메시지를 돌려준다. API 오류는 한국어 LLMError 로 바꾼다."""
    try:
        with client.beta.messages.stream(**_model_kwargs(), **kwargs) as stream:
            return stream.get_final_message()
    except anthropic.AuthenticationError as e:
        raise LLMError("Anthropic API 키가 올바르지 않습니다. '설정' 탭(또는 .env)의 Claude API 키를 확인하세요.") from e
    except anthropic.PermissionDeniedError as e:
        raise LLMError("이 API 키로는 요청한 기능을 쓸 수 없습니다. Anthropic 콘솔에서 웹 검색 사용 여부를 확인하세요.") from e
    except anthropic.RateLimitError as e:
        raise LLMError("API 호출 한도를 초과했습니다. 잠시 후 다시 시도하세요.") from e
    except anthropic.APIStatusError as e:
        if "credit balance" in str(e.message).lower():
            raise LLMError("Claude API 크레딧이 부족합니다. console.anthropic.com → Settings → Billing 에서 "
                           "크레딧을 충전한 뒤 다시 시도하세요. (Claude 앱 구독과 API 크레딧은 따로 결제돼요)") from e
        raise LLMError(f"Claude API 오류 ({e.status_code}): {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise LLMError("Claude API 에 연결하지 못했습니다. 네트워크를 확인하세요.") from e


def _check_stop(message: Any) -> None:
    if message.stop_reason == "refusal":
        raise LLMError("모델이 이 요청을 처리하지 않았습니다. 주제나 참고자료를 바꿔 다시 시도하세요.")
    if message.stop_reason == "max_tokens":
        raise LLMError("응답이 너무 길어 잘렸습니다. 섹션 수나 목표 글자수를 줄여 주세요.")


def generate_json(
    system: str,
    prompt: str,
    schema: dict[str, Any],
    *,
    effort: str = "high",
    max_tokens: int = 32000,
) -> dict[str, Any]:
    message = _stream(
        anthropic.Anthropic(),
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        thinking={"type": "adaptive"},
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
    )
    _check_stop(message)
    text = next((b.text for b in message.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError("모델 응답을 JSON 으로 해석하지 못했습니다.") from e


def _collect_sources(content: list[Any], sources: dict[str, str]) -> None:
    """응답 블록에서 검색 결과·열어 본 페이지·인용 출처의 (주소 → 제목)을 모은다."""
    for block in content:
        btype = getattr(block, "type", "")
        if btype == "web_search_tool_result":
            results = getattr(block, "content", None)
            if isinstance(results, list):  # 오류일 때는 목록이 아니라 객체가 온다
                for r in results:
                    url = getattr(r, "url", "")
                    if url:
                        sources.setdefault(url, getattr(r, "title", "") or url)
        elif btype == "web_fetch_tool_result":
            result = getattr(block, "content", None)
            url = getattr(result, "url", "")
            if url:
                doc = getattr(result, "content", None)
                sources.setdefault(url, getattr(doc, "title", "") or url)
        elif btype == "text":
            for c in getattr(block, "citations", None) or []:
                url = getattr(c, "url", "")
                if url:
                    sources[url] = getattr(c, "title", "") or sources.get(url, url)


def _cited_urls(content: list[Any]) -> list[str]:
    urls: list[str] = []
    for block in content:
        if getattr(block, "type", "") == "text":
            for c in getattr(block, "citations", None) or []:
                url = getattr(c, "url", "")
                if url and url not in urls:
                    urls.append(url)
    return urls


def web_research(
    system: str,
    prompt: str,
    *,
    max_searches: int = 8,
    max_fetches: int = 6,
    effort: str = "high",
    max_tokens: int = 64000,
    client_factory: Callable[[], Any] = anthropic.Anthropic,
) -> tuple[str, list[dict[str, str]]]:
    """웹 검색으로 조사한 결과 글과 출처 목록을 돌려준다.

    출처 목록은 본문에서 실제로 인용한 페이지를 앞에 두고, 그 밖에 검색·열람한 페이지를 뒤에 둔다.
    """
    client = client_factory()
    tools = [
        {"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches,
         "user_location": {"type": "approximate", "country": "KR", "timezone": "Asia/Seoul"}},
        {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": max_fetches},
    ]
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    content: list[Any] = []
    sources: dict[str, str] = {}
    for _ in range(MAX_CONTINUATIONS + 1):
        message = _stream(
            client,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=tools,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
        )
        _check_stop(message)
        content += list(message.content)
        _collect_sources(message.content, sources)
        if message.stop_reason != "pause_turn":
            break
        # 서버 쪽 검색이 길어져 멈춘 경우: 지금까지의 응답을 그대로 붙여 다시 보내면 이어서 진행된다
        messages = [{"role": "user", "content": prompt}, {"role": "assistant", "content": message.content}]
    else:
        raise LLMError("웹 조사가 너무 오래 걸려 중단했습니다. 주제를 좁혀 다시 시도하세요.")

    text = "".join(b.text for b in content if getattr(b, "type", "") == "text").strip()
    if not text:
        raise LLMError("웹 조사 결과가 비어 있습니다. 잠시 후 다시 시도하세요.")
    cited = _cited_urls(content)
    ordered = cited + [u for u in sources if u not in cited]
    return text, [{"url": u, "title": sources.get(u, u)} for u in ordered]
