"""정부·공공기관 사이트의 새 게시물(RSS/게시판)을 감시해 알림을 보낸다."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import feedparser
import requests
from bs4 import BeautifulSoup

from ..config import resolve
from . import notify

UA = {"User-Agent": "Mozilla/5.0 (blogauto monitor)"}
MAX_SEEN = 1000


def fetch_rss(url: str, session: requests.Session) -> list[dict[str, str]]:
    resp = session.get(url, headers=UA, timeout=20)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    return [
        {"id": e.get("id") or e.get("link", ""), "title": e.get("title", "").strip(),
         "link": e.get("link", ""), "date": e.get("published", "")}
        for e in feed.entries
    ]


def fetch_html(url: str, selector: str, session: requests.Session) -> list[dict[str, str]]:
    resp = session.get(url, headers=UA, timeout=20)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or resp.encoding
    soup = BeautifulSoup(resp.text, "html.parser")
    items = []
    for a in soup.select(selector):
        title = " ".join(a.get_text(" ").split())
        href = a.get("href", "")
        # javascript: 링크 게시판은 제목을 식별자로 사용
        link = urljoin(url, href) if href and not href.startswith("javascript") else url
        items.append({"id": link if link != url else title, "title": title, "link": link, "date": ""})
    return items


def matches(title: str, include: list[str], exclude: list[str]) -> bool:
    if any(w in title for w in exclude):
        return False
    return not include or any(w in title for w in include)


def _load_state(path: Path) -> dict[str, list[str]]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def run(settings: dict[str, Any], dry_run: bool = False, notify_initial: bool = False,
        session: requests.Session | None = None) -> dict[str, Any]:
    cfg = settings.get("monitor", {})
    session = session or requests.Session()
    state_path = resolve(cfg.get("state_file", "data/monitor_state.json"))
    state = _load_state(state_path)
    include, exclude = cfg.get("include_keywords", []), cfg.get("exclude_keywords", [])

    new_items: list[dict[str, str]] = []
    errors: list[str] = []
    for src in cfg.get("sources", []):
        name = src["name"]
        try:
            if src.get("type", "rss") == "rss":
                items = fetch_rss(src["url"], session)
            else:
                items = fetch_html(src["url"], src["link_selector"], session)
        except Exception as e:  # 한 사이트 실패가 전체를 막지 않도록
            errors.append(f"{name}: {e}")
            continue

        first_run = name not in state
        seen = set(state.get(name, []))
        fresh = [it for it in items if it["id"] and it["id"] not in seen]
        if not first_run or notify_initial:
            new_items.extend({**it, "source": name} for it in fresh if matches(it["title"], include, exclude))
        state[name] = ([it["id"] for it in fresh] + state.get(name, []))[:MAX_SEEN]

    if errors:
        print("[모니터링] 일부 사이트 수집 실패:\n  " + "\n  ".join(errors))

    if not dry_run:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")

    if new_items:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [f"📢 새 공고 {len(new_items)}건 ({now})"]
        lines += [f"\n[{it['source']}] {it['title']}\n{it['link']}" for it in new_items]
        text = "\n".join(lines)
        if dry_run:
            print(text)
        else:
            notify.send(text)
            out_dir = resolve(cfg.get("output_dir", "output/monitor"))
            out_dir.mkdir(parents=True, exist_ok=True)
            log = out_dir / f"{datetime.now():%Y-%m-%d}.md"
            with log.open("a", encoding="utf-8") as f:
                f.write(f"\n## {now}\n\n" + "\n".join(f"- [{it['source']}] [{it['title']}]({it['link']})" for it in new_items) + "\n")
    return {"new": new_items, "errors": errors}
