import json
import shutil
from pathlib import Path

import pytest

from blogauto import config

REPO = Path(__file__).resolve().parent.parent


class FakeResponse:
    def __init__(self, status=200, payload=None, content=b"", text=""):
        self.status_code = status
        self._payload = payload
        self.content = content
        self.text = text or (json.dumps(payload) if payload is not None else content.decode("utf-8", "ignore"))
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    """URL 부분 문자열 → 응답(또는 요청을 받아 응답을 만드는 함수)."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def _handle(self, method, url, **kw):
        self.calls.append((method, url, kw))
        for key, resp in self.routes.items():
            if key in url:
                return resp(kw) if callable(resp) else resp
        raise AssertionError(f"예상하지 못한 요청: {url}")

    def get(self, url, **kw):
        return self._handle("GET", url, **kw)

    def post(self, url, **kw):
        return self._handle("POST", url, **kw)


@pytest.fixture
def project(tmp_path, monkeypatch):
    """임시 프로젝트 루트 (config 복사)."""
    shutil.copytree(REPO / "config", tmp_path / "config")
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(config, "ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def settings(project):
    return config.load_settings(project / "config" / "settings.yaml")


@pytest.fixture
def sample_meta():
    return {
        "topic": "2026 근로장려금 신청 방법",
        "main_keyword": "근로장려금",
        "titles": [f"2026 근로장려금 신청방법 총정리 {i}" for i in range(5)],
        "intro": "근로장려금 받을 수 있는지 궁금하셨죠? 오늘은 근로장려금 신청 방법을 정리해 볼게요.",
        "sections": [
            {"heading": "근로장려금이란?", "quote": "일하는 저소득 가구를 위한 *지원금*",
             "body": "근로장려금은 일은 하지만 소득이 적은 가구를 돕는 제도예요.\n지급액은 [확인 필요]예요.",
             "card_caption": "제도 한 줄 요약"},
            {"heading": "신청 대상과 소득 기준 한눈에 보기", "quote": "가구 유형별로 기준이 달라요",
             "body": "단독가구, 홑벌이, 맞벌이 가구마다 기준이 달라요.\n1. 단독가구\n2. 홑벌이 가구\n3. 맞벌이 가구",
             "card_caption": "가구 유형별 기준"},
            {"heading": "지급액 계산 방법", "quote": "소득 구간별로 달라져요", "body": "계산 방법이에요.", "card_caption": ""},
            {"heading": "홈택스 신청 방법 단계별 안내", "quote": "5분이면 끝나요", "body": "신청 방법이에요.", "card_caption": "신청 절차"},
            {"heading": "자주 하는 실수", "quote": "", "body": "실수 사례예요.", "card_caption": ""},
        ],
        "image_sections": [2, 4],
        "outro": "도움이 되셨다면 공감과 이웃추가 부탁드려요.",
        "summary": ["근로장려금은 저소득 근로 가구 지원 제도", "가구 유형별 소득 기준 확인", "홈택스에서 신청"],
        "hashtags": ["근로장려금", "근로장려금신청", "장려금"],
        "thumbnail_texts": [{"main": "2026 *근로장려금*\n신청 총정리", "sub": "대상·금액·기간 한 번에"},
                            {"main": "근로장려금 *반기 신청*", "sub": "놓치면 손해"}],
        "fact_check": ["2026년 최대 지급액"],
    }
