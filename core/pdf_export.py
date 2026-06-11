"""개발목록 → A4 페이지당 항목 1개 PDF 생성 (개발사 API 요청 송부용).

각 항목 한 페이지에 제목 + 메타(상태/담당자/등록일) + 설명 + 첨부 이미지를 담는다.
별도 의존성 없이 Pillow 만으로 멀티페이지 PDF 를 만든다 (PDF 첨부는 표시 대상 아님).

한글 폰트는 Windows 맑은 고딕(malgun.ttf)을 우선 사용하고, 없으면 기본 폰트로
폴백한다(이 경우 한글이 깨질 수 있음).
"""

from __future__ import annotations

import io
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

from . import paths
from .workflow import STATUS_LABELS_KO

# A4 비율 @ ~150dpi — 용량과 가독성의 균형.
A4_W, A4_H = 1240, 1754
MARGIN = 70

_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\malgun.ttf",
    r"C:\Windows\Fonts\malgunbd.ttf",
    r"C:\Windows\Fonts\gulim.ttc",
    r"C:\Windows\Fonts\batang.ttc",
]


def _load_font(size: int) -> ImageFont.ImageFont:
    for fp in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(fp, size)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    """max_w 폭에 맞춰 줄바꿈 — 한글은 단어 경계가 없어 문자 단위로 자른다."""
    lines: list[str] = []
    for para in (text or "").split("\n"):
        if not para:
            lines.append("")
            continue
        cur = ""
        for ch in para:
            if draw.textlength(cur + ch, font=font) <= max_w:
                cur += ch
            else:
                lines.append(cur)
                cur = ch
        lines.append(cur)
    return lines


def _render_page(issue) -> Image.Image:
    page = Image.new("RGB", (A4_W, A4_H), "white")
    draw = ImageDraw.Draw(page)
    title_font = _load_font(44)
    meta_font = _load_font(26)
    body_font = _load_font(30)
    content_w = A4_W - 2 * MARGIN
    y = MARGIN

    # 제목
    for line in _wrap(draw, issue.title, title_font, content_w):
        draw.text((MARGIN, y), line, font=title_font, fill=(17, 24, 39))
        y += 56
    y += 8

    # 메타
    _status = STATUS_LABELS_KO.get(issue.status, getattr(issue.status, "value", ""))
    meta = (
        f"상태: {_status}   |   담당: {issue.assignee or '-'}   |   "
        f"등록: {str(issue.created_at)[:10]}"
    )
    draw.text((MARGIN, y), meta, font=meta_font, fill=(107, 114, 128))
    y += 40
    draw.line([(MARGIN, y), (A4_W - MARGIN, y)], fill=(209, 213, 219), width=2)
    y += 24

    # 설명 (이미지 공간을 남기기 위해 페이지 절반까지만)
    desc_limit_y = int(A4_H * 0.5)
    for line in _wrap(draw, issue.description or "", body_font, content_w):
        if y > desc_limit_y:
            draw.text((MARGIN, y), "…", font=body_font, fill=(30, 30, 30))
            y += 40
            break
        draw.text((MARGIN, y), line, font=body_font, fill=(31, 41, 55))
        y += 42
    y += 16

    # 첨부 이미지 — 남은 세로 공간에 순서대로 배치 (PDF 첨부는 건너뜀).
    item_dir = paths.item_dir(issue.id)
    for img_ref in issue.images:
        if str(img_ref.file).lower().endswith(".pdf"):
            continue
        img_path = item_dir / img_ref.file
        if not img_path.exists():
            continue
        avail_h = A4_H - MARGIN - y
        if avail_h < 120:
            break
        try:
            with Image.open(img_path) as im:
                im = im.convert("RGB")
                im.thumbnail((content_w, avail_h))
                page.paste(im, (MARGIN, y))
                y += im.height + 18
        except Exception:  # noqa: BLE001
            continue

    return page


def build_issues_pdf(issues: Iterable) -> bytes:
    """Issue 들을 A4 페이지당 1개로 그려 PDF bytes 로 반환."""
    pages = [_render_page(iss) for iss in issues]
    if not pages:
        pages = [Image.new("RGB", (A4_W, A4_H), "white")]
    buf = io.BytesIO()
    pages[0].save(
        buf,
        format="PDF",
        save_all=True,
        append_images=pages[1:],
        resolution=150.0,
    )
    return buf.getvalue()


__all__ = ["build_issues_pdf"]
