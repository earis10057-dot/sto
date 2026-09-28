"""블로그 글마다 썸네일(1:1) 1장과 본문 이미지(16:9) 4장을 만든다 (Pillow)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from ..layout import BODY_SIZE, THUMBNAIL, THUMB_SIZE, body_images
from .fonts import find_font


@dataclass(frozen=True)
class Theme:
    bg: str      # 썸네일 배경(위)
    bg2: str     # 썸네일 배경(아래)
    text: str    # 어두운 배경 위 글자
    sub: str     # 어두운 배경 위 보조 글자
    accent: str  # 강조색
    light: str   # 밝은 카드 배경
    ink: str     # 밝은 배경 위 글자


THEMES = {
    "navy": Theme("#1B2A4A", "#2F4B7C", "#FFFFFF", "#C9D6EA", "#FFD43B", "#F4F7FC", "#1B2A4A"),
    "mint": Theme("#0F766E", "#14B8A6", "#FFFFFF", "#CCFBF1", "#FDE047", "#F0FDFA", "#134E4A"),
    "coral": Theme("#C2410C", "#F97316", "#FFFFFF", "#FFEDD5", "#FFF3BF", "#FFF7ED", "#7C2D12"),
    "mono": Theme("#111111", "#3A3A3A", "#FFFFFF", "#D4D4D4", "#FF6B6B", "#F5F5F5", "#111111"),
    "forest": Theme("#1E3A2B", "#2D6A4F", "#FFFFFF", "#D8F3DC", "#F4D35E", "#F1F8F4", "#1E3A2B"),
}

Run = tuple[str, bool]  # (글자, 강조 여부)


@lru_cache(maxsize=64)
def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def parse_emphasis(text: str) -> list[Run]:
    """'*강조*' 표기를 (글자, 강조) 목록으로 바꾼다."""
    out: list[Run] = []
    hl = False
    for part in re.split(r"(\*)", text):
        if part == "*":
            hl = not hl
        else:
            out += [(ch, hl) for ch in part]
    return out


def _width(chars: list[Run], font) -> float:
    return font.getlength("".join(c for c, _ in chars))


def wrap(runs: list[Run], font, max_w: float) -> list[list[Run]]:
    """단어(띄어쓰기) 단위로 줄바꿈하고, 한 단어가 너무 길면 글자 단위로 자른다."""
    lines: list[list[Run]] = []
    for para in _split(runs, "\n"):
        line: list[Run] = []
        for word in _split(para, " "):
            if not word:
                continue
            cand = line + ([(" ", False)] if line else []) + word
            if _width(cand, font) <= max_w:
                line = cand
                continue
            if line:
                lines.append(line)
                line = []
            for ch in word:  # 긴 단어를 글자 단위로
                if line and _width(line + [ch], font) > max_w:
                    lines.append(line)
                    line = []
                line.append(ch)
        lines.append(line)
    return [ln for ln in lines if ln] or [[]]


def _split(runs: list[Run], sep: str) -> list[list[Run]]:
    out: list[list[Run]] = [[]]
    for r in runs:
        if r[0] == sep:
            out.append([])
        else:
            out[-1].append(r)
    return out


def fit_text(text: str, font_path: str, max_w: int, max_h: int, max_lines: int,
             size_max: int, size_min: int, line_gap: float = 1.25):
    """박스에 들어가는 가장 큰 글자 크기를 찾는다."""
    runs = parse_emphasis(text)
    size = size_max
    while True:
        font = _font(font_path, size)
        lines = wrap(runs, font, max_w)
        height = int(size * line_gap) * len(lines)
        if (len(lines) <= max_lines and height <= max_h) or size <= size_min:
            return font, lines, int(size * line_gap)
        size -= 4


def draw_lines(draw: ImageDraw.ImageDraw, lines: list[list[Run]], font, x: int, y: int, line_h: int,
               color: str, hl_color: str, align: str = "left", box_w: int = 0) -> int:
    for line in lines:
        w = _width(line, font)
        cx = x + (box_w - w) / 2 if align == "center" else x
        # 연속된 같은 스타일 글자를 묶어서 그림
        seg, seg_hl = "", None
        for ch, hl in line + [("", None)]:
            if hl != seg_hl and seg:
                draw.text((cx, y), seg, font=font, fill=hl_color if seg_hl else color)
                cx += font.getlength(seg)
                seg = ""
            seg += ch
            seg_hl = hl
        y += line_h
    return y


def _gradient(w: int, h: int, top: str, bottom: str) -> Image.Image:
    t, b = Image.new("RGB", (1, 1), top).getpixel((0, 0)), Image.new("RGB", (1, 1), bottom).getpixel((0, 0))
    col = Image.new("RGB", (1, h))
    for y in range(h):
        r = y / max(h - 1, 1)
        col.putpixel((0, y), tuple(int(t[i] + (b[i] - t[i]) * r) for i in range(3)))
    return col.resize((w, h))


def _decor(img: Image.Image, color: str) -> None:
    """배경에 반투명 원 장식."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    w, h = img.size
    rgb = Image.new("RGB", (1, 1), color).getpixel((0, 0))
    d.ellipse((w * 0.62, -h * 0.18, w * 1.25, h * 0.45), fill=(*rgb, 22))
    d.ellipse((-w * 0.25, h * 0.72, w * 0.3, h * 1.25), fill=(*rgb, 16))
    img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"))


def thumbnail(main: str, sub: str, out: Path, theme: Theme, bold: str, regular: str,
              badge: str = "", blog_name: str = "", size: int = 1080) -> Path:
    img = _gradient(size, size, theme.bg, theme.bg2)
    _decor(img, "#FFFFFF")
    d = ImageDraw.Draw(img)
    pad = int(size * 0.08)

    if badge:
        bf = _font(bold, int(size * 0.036))
        bw = bf.getlength(badge)
        bh = int(size * 0.036 * 1.9)
        d.rounded_rectangle((pad, pad, pad + bw + bh, pad + bh), radius=bh // 2, fill=theme.accent)
        d.text((pad + bh / 2, pad + bh / 2), badge, font=bf, fill=theme.ink, anchor="lm")

    box_w = size - pad * 2
    font, lines, lh = fit_text(main, bold, box_w, int(size * 0.5), 3, int(size * 0.13), int(size * 0.06))
    sub_font, sub_lines, sub_lh = fit_text(sub, regular, box_w, int(size * 0.14), 2, int(size * 0.045), int(size * 0.03))
    block_h = lh * len(lines) + (int(size * 0.05) + sub_lh * len(sub_lines) if sub else 0)
    y = (size - block_h) // 2
    y = draw_lines(d, lines, font, pad, y, lh, theme.text, theme.accent)
    if sub:
        y += int(size * 0.02)
        d.rectangle((pad, y, pad + int(size * 0.08), y + int(size * 0.008)), fill=theme.accent)
        y += int(size * 0.03)
        draw_lines(d, sub_lines, sub_font, pad, y, sub_lh, theme.sub, theme.accent)

    if blog_name:
        nf = _font(regular, int(size * 0.03))
        d.text((size - pad, size - pad), blog_name, font=nf, fill=theme.sub, anchor="rb")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def _one_line(d: ImageDraw.ImageDraw, text: str, font, x: float, y: float, max_w: float, fill: str) -> None:
    """한 줄에 안 들어가면 말줄임표로 자른다."""
    if font.getlength(text) > max_w:
        while text and font.getlength(text + "…") > max_w:
            text = text[:-1]
        text += "…"
    d.text((x, y), text, font=font, fill=fill, anchor="lm")


def contents_card(title: str, headings: list[str], out: Path, theme: Theme, bold: str, regular: str,
                  size: tuple[int, int] = BODY_SIZE) -> Path:
    """도입부 다음에 넣는 목차 카드."""
    w, h = size
    img = _gradient(w, h, theme.bg, theme.bg2)
    _decor(img, "#FFFFFF")
    d = ImageDraw.Draw(img)
    pad = int(h * 0.1)

    left_w = int(w * 0.36)
    d.text((pad, pad), "CONTENTS", font=_font(bold, int(h * 0.04)), fill=theme.accent)
    tf, tlines, tlh = fit_text(title, bold, left_w - pad, int(h * 0.5), 4, int(h * 0.085), int(h * 0.05))
    y = draw_lines(d, tlines, tf, pad, pad + int(h * 0.1), tlh, theme.text, theme.accent)
    d.text((pad, y + int(h * 0.03)), "이 글에서 알려드릴 내용", font=_font(regular, int(h * 0.035)), fill=theme.sub)

    box = (left_w + int(w * 0.04), pad, w - pad, h - pad)
    d.rounded_rectangle(box, radius=int(h * 0.03), fill=theme.light)
    items = headings[:6]
    row_h = (box[3] - box[1]) / max(len(items), 1)
    size_px = int(min(row_h * 0.36, h * 0.048))
    hf, nf = _font(bold, size_px), _font(bold, int(size_px * 0.8))
    r = int(size_px * 0.85)
    for i, text in enumerate(items, 1):
        cy = box[1] + row_h * (i - 0.5)
        cx = box[0] + int(w * 0.035) + r
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=theme.bg2)
        d.text((cx, cy), str(i), font=nf, fill="#FFFFFF", anchor="mm")
        _one_line(d, text, hf, cx + r + int(w * 0.02), cy, box[2] - (cx + r) - int(w * 0.045), theme.ink)
        if i < len(items):
            ly = box[1] + row_h * i
            d.line((box[0] + int(w * 0.03), ly, box[2] - int(w * 0.03), ly), fill="#DDE3EC", width=2)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def section_card(index: int, heading: str, quote: str, caption: str, out: Path, theme: Theme,
                 bold: str, regular: str, size: tuple[int, int] = BODY_SIZE) -> Path:
    """핵심 소제목 위에 넣는 카드: 번호 + 소제목 + 핵심 한 줄."""
    w, h = size
    img = Image.new("RGB", (w, h), theme.light)
    d = ImageDraw.Draw(img)
    pad = int(h * 0.11)
    d.rectangle((0, 0, int(h * 0.025), h), fill=theme.bg2)

    nf = _font(bold, int(h * 0.16))
    num = f"{index:02d}"
    d.text((pad, pad), num, font=nf, fill=theme.bg2, anchor="lt")
    label = "POINT" + (f"  ·  {caption}" if caption else "")
    lx = pad + nf.getlength(num) + int(h * 0.04)
    _one_line(d, label, _font(bold, int(h * 0.036)), lx, pad + int(h * 0.08), w - lx - pad, theme.bg2)

    font, lines, lh = fit_text(heading, bold, w - pad * 2, int(h * 0.3), 2, int(h * 0.1), int(h * 0.055))
    y = draw_lines(d, lines, font, pad, int(h * 0.36), lh, theme.ink, theme.bg2)

    if quote:
        qf, qlines, qlh = fit_text(quote, regular, w - pad * 2 - int(h * 0.1), int(h * 0.16), 2,
                                   int(h * 0.05), int(h * 0.034))
        top = max(y + int(h * 0.04), h - pad - qlh * len(qlines) - int(h * 0.06))
        bottom = top + qlh * len(qlines) + int(h * 0.06)
        d.rounded_rectangle((pad, top, w - pad, bottom), radius=int(h * 0.02), fill="#FFFFFF")
        d.rectangle((pad, top, pad + int(h * 0.012), bottom), fill=theme.accent)
        draw_lines(d, qlines, qf, pad + int(h * 0.05), top + int(h * 0.03), qlh, theme.ink, theme.bg2)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def summary_card(title: str, points: list[str], out: Path, theme: Theme, bold: str, regular: str,
                 size: tuple[int, int] = BODY_SIZE) -> Path:
    """마무리 '한눈에 정리' 위에 넣는 요약 카드."""
    w, h = size
    img = Image.new("RGB", (w, h), theme.light)
    left_w = int(w * 0.34)
    img.paste(_gradient(left_w, h, theme.bg, theme.bg2), (0, 0))
    d = ImageDraw.Draw(img)
    pad = int(h * 0.1)

    d.text((pad, pad), "한눈에 정리", font=_font(bold, int(h * 0.045)), fill=theme.accent)
    tf, tlines, tlh = fit_text(title, bold, left_w - pad * 2 + int(h * 0.04), int(h * 0.55), 4,
                               int(h * 0.08), int(h * 0.045))
    draw_lines(d, tlines, tf, pad, pad + int(h * 0.12), tlh, theme.text, theme.accent)

    items = points[:5]
    x0 = left_w + int(w * 0.05)
    row_h = (h - pad * 2) / max(len(items), 1)
    r = int(h * 0.028)
    text_x = x0 + r * 2 + int(w * 0.02)
    for i, p in enumerate(items):
        pf, plines, plh = fit_text(p, regular, w - text_x - pad, int(row_h * 0.85), 2, int(h * 0.045), int(h * 0.03))
        block = plh * len(plines)
        top = pad + row_h * i + (row_h - block) / 2
        cy = top + plh / 2
        d.ellipse((x0, cy - r, x0 + 2 * r, cy + r), fill=theme.bg2)
        d.line((x0 + r * 0.5, cy, x0 + r * 0.9, cy + r * 0.4, x0 + r * 1.5, cy - r * 0.4),
               fill="#FFFFFF", width=max(3, r // 5))
        draw_lines(d, plines, pf, text_x, int(top), plh, theme.ink, theme.bg2)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def _clean(text: str) -> str:
    """이미지에는 '[확인 필요]' 같은 작성용 표시를 넣지 않는다."""
    return re.sub(r"\s*\[확인 필요\]", "", text or "").strip()


def render_post(meta: dict[str, Any], post_dir: Path, icfg: dict[str, Any], theme_name: str | None = None,
                thumb: int = 1) -> list[Path]:
    """썸네일 1장(1:1) + 본문 이미지 4장(16:9)을 post_dir/images 에 만든다.

    thumb: meta 의 썸네일 문구 후보 중 몇 번째를 쓸지 (1부터)
    """
    theme = THEMES.get(theme_name or icfg.get("theme", "navy"), THEMES["navy"])
    bold = find_font(True, icfg.get("font_bold", ""))
    regular = find_font(False, icfg.get("font_regular", ""))
    title = meta.get("main_keyword") or meta.get("topic", "")
    sections = meta.get("sections", [])
    img_dir = post_dir / "images"
    for old in img_dir.glob("*.png") if img_dir.exists() else []:
        old.unlink()  # 이전 구성의 이미지가 남지 않도록

    texts = meta.get("thumbnail_texts") or [{"main": title, "sub": ""}]
    t = texts[min(max(thumb, 1), len(texts)) - 1]
    paths = [thumbnail(_clean(t["main"]), _clean(t.get("sub", "")), post_dir / THUMBNAIL, theme, bold, regular,
                       badge=icfg.get("badge", ""), blog_name=icfg.get("blog_name", ""), size=THUMB_SIZE[0])]

    plan = body_images(meta)
    paths.append(contents_card(meta.get("topic") or title, [_clean(s["heading"]) for s in sections],
                               post_dir / plan["contents"], theme, bold, regular))
    for i, rel in plan["sections"].items():
        sec = sections[i - 1]
        paths.append(section_card(i, _clean(sec["heading"]), _clean(sec.get("quote", "")), _clean(sec.get("card_caption", "")),
                                  post_dir / rel, theme, bold, regular))
    paths.append(summary_card(title, [_clean(p) for p in meta.get("summary", [])], post_dir / plan["summary"], theme, bold, regular))
    return paths
