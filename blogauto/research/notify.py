"""알림 전송: 콘솔 + (설정 시) 텔레그램 / 디스코드·슬랙 웹훅."""
from __future__ import annotations

import os

import requests


def send(text: str) -> list[str]:
    """보낸 채널 이름 목록을 반환한다."""
    sent = ["console"]
    print(text)

    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if token and chat:
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": text[:4000], "disable_web_page_preview": True},
                timeout=15,
            ).raise_for_status()
            sent.append("telegram")
        except requests.RequestException as e:
            print(f"[알림] 텔레그램 전송 실패: {e}")

    hook = os.getenv("WEBHOOK_URL")
    if hook:
        # 디스코드는 content, 슬랙은 text 키를 쓴다
        payload = {"content": text[:1900]} if "discord" in hook else {"text": text}
        try:
            requests.post(hook, json=payload, timeout=15).raise_for_status()
            sent.append("webhook")
        except requests.RequestException as e:
            print(f"[알림] 웹훅 전송 실패: {e}")
    return sent
