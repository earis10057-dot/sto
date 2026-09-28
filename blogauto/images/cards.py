"""블로그 글마다 썸네일·섹션 카드·요약 카드 이미지를 만든다 (Pillow)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

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


def section_card(index: int, heading: str, caption: str, out: Path, theme: Theme, bold: str, regular: str,
                 w: int = 1080, h: int = 720) -> Path:
    img = Image.new("RGB", (w, h), theme.light)
    d = ImageDraw.Draw(img)
    pad = int(w * 0.08)
    d.rectangle((0, 0, int(w * 0.018), h), fill=theme.bg2)

    nf = _font(bold, int(h * 0.2))
    d.text((pad, int(h * 0.12)), f"{index:02d}", font=nf, fill=theme.bg2)
    lf = _font(bold, int(h * 0.04))
    d.text((pad + nf.getlength(f"{index:02d}") + 24, int(h * 0.12) + int(h * 0.05)), "POINT", font=lf, fill=theme.bg2)

    font, lines, lh = fit_text(heading, bold, w - pad * 2, int(h * 0.36), 2, int(h * 0.11), int(h * 0.06))
    y = int(h * 0.42)
    y = draw_lines(d, lines, font, pad, y, lh, theme.ink, theme.bg2)
    if caption:
        y += int(h * 0.04)
        cf, clines, clh = fit_text(caption, regular, w - pad * 2, int(h * 0.12), 2, int(h * 0.05), int(h * 0.035))
        draw_lines(d, clines, cf, pad, y, clh, "#666666", theme.bg2)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def summary_card(title: str, points: list[str], out: Path, theme: Theme, bold: str, regular: str,
                 w: int = 1080, h: int = 1350) -> Path:
    img = Image.new("RGB", (w, h), theme.light)
    d = ImageDraw.Draw(img)
    pad = int(w * 0.08)
    header_h = int(h * 0.22)
    img.paste(_gradient(w, header_h, theme.bg, theme.bg2), (0, 0))
    d.text((pad, int(header_h * 0.3)), "한눈에 정리", font=_font(bold, int(w * 0.035)), fill=theme.accent)
    tf, tlines, tlh = fit_text(title, bold, w - pad * 2, int(header_h * 0.45), 2, int(w * 0.06), int(w * 0.04))
    draw_lines(d, tlines, tf, pad, int(header_h * 0.48), tlh, theme.text, theme.accent)

    y = header_h + int(h * 0.05)
    avail = h - y - pad
    per = avail // max(len(points), 1)
    r = int(w * 0.028)
    text_x = pad + r * 2 + 28
    for p in points:
        pf, plines, plh = fit_text(p, regular, w - text_x - pad, per - 30, 3, int(w * 0.042), int(w * 0.03))
        cy = y + plh // 2
        d.ellipse((pad, cy - r, pad + 2 * r, cy + r), fill=theme.bg2)
        d.line((pad + r * 0.5, cy, pad + r * 0.9, cy + r * 0.4, pad + r * 1.5, cy - r * 0.4),
               fill="#FFFFFF", width=max(3, r // 5))
        draw_lines(d, plines, pf, text_x, y, plh, theme.ink, theme.bg2)
        y += per
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def render_post(meta: dict[str, Any], post_dir: Path, icfg: dict[str, Any], theme_name: str | None = None) -> list[Path]:
    """meta.json 한 편에 대한 이미지 전체를 post_dir/images 에 생성한다."""
    theme = THEMES.get(theme_name or icfg.get("theme", "navy"), THEMES["navy"])
    bold = find_font(True, icfg.get("font_bold", ""))
    regular = find_font(False, icfg.get("font_regular", ""))
    img_dir = post_dir / "images"
    paths: list[Path] = []

    for i, t in enumerate(meta.get("thumbnail_texts", []), 1):
        paths.append(thumbnail(t["main"], t.get("sub", ""), img_dir / f"thumbnail_{i}.png", theme, bold, regular,
                               badge=icfg.get("badge", ""), blog_name=icfg.get("blog_name", "")))
    for i, sec in enumerate(meta.get("sections", []), 1):
        paths.append(section_card(i, sec["heading"], sec.get("card_caption", ""),
                                  img_dir / f"section_{i:02d}.png", theme, bold, regular))
    if meta.get("summary"):
        title = meta.get("main_keyword") or meta.get("topic", "")
        paths.append(summary_card(title, meta["summary"], img_dir / "summary.png", theme, bold, regular))
    return paths
