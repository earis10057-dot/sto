"""Claude 호출 공통 모듈: JSON 스키마로 구조화된 응답을 받는다."""
from __future__ import annotations

import json
import os
from typing import Any

import anthropic

DEFAULT_MODEL = "claude-opus-5"
# 안전 분류기가 요청을 거절하면 서버가 다른 모델로 자동 재시도하도록 하는 옵션
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    pass


def model_name() -> str:
    return os.getenv("BLOGAUTO_MODEL", DEFAULT_MODEL)


def generate_json(
    system: str,
    prompt: str,
    schema: dict[str, Any],
    *,
    effort: str = "high",
    max_tokens: int = 32000,
) -> dict[str, Any]:
    client = anthropic.Anthropic()
    model = model_name()
    kwargs: dict[str, Any] = {}
    if model.startswith(("claude-opus-5", "claude-fable-5")):
        kwargs = {"betas": [FALLBACK_BETA], "fallbacks": "default"}

    try:
        with client.beta.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            thinking={"type": "adaptive"},
            output_config={
                "effort": effort,
                "format": {"type": "json_schema", "schema": schema},
            },
            **kwargs,
        ) as stream:
            message = stream.get_final_message()
    except anthropic.AuthenticationError as e:
        raise LLMError("Anthropic API 키가 올바르지 않습니다. .env 의 ANTHROPIC_API_KEY 를 확인하세요.") from e
    except anthropic.RateLimitError as e:
        raise LLMError("API 호출 한도를 초과했습니다. 잠시 후 다시 시도하세요.") from e
    except anthropic.APIStatusError as e:
        raise LLMError(f"Claude API 오류 ({e.status_code}): {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise LLMError("Claude API 에 연결하지 못했습니다. 네트워크를 확인하세요.") from e

    if message.stop_reason == "refusal":
        raise LLMError("모델이 이 요청을 처리하지 않았습니다. 주제나 참고자료를 바꿔 다시 시도하세요.")
    if message.stop_reason == "max_tokens":
        raise LLMError("응답이 너무 길어 잘렸습니다. 섹션 수나 목표 글자수를 줄여 주세요.")

    text = next((b.text for b in message.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError("모델 응답을 JSON 으로 해석하지 못했습니다.") from e
