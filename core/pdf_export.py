"""개발사 요청 PDF 생성 (가로/landscape, 페이지당 항목 1개).

각 항목 한 페이지에 제목 + 설명 + 마지막 타임라인 코멘트(있으면) + 첨부 이미지를
담는다. 개발사에 송부하는 용도라 상태/담당/등록일 같은 내부 메타는 싣지 않는다 (7번).

첨부 이미지는 크기가 제각각이므로 균일한 셀(grid)에 각자 비율을 유지한 채 맞춰
넣어(thumbnail) 가운데 정렬한다 — 한 장이 과도하게 크거나 작지 않게 보인다.

한글 폰트는 Windows 맑은 고딕(malgun.ttf)을 우선 사용하고, 없으면 기본 폰트로
폴백한다(이 경우 한글이 깨질 수 있음).
"""

from __future__ import annotations

import io
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

from . import paths
from .models import Comment

# A4 가로(landscape) @ ~150dpi — 용량과 가독성의 균형.
PAGE_W, PAGE_H = 1754, 1240
MARGIN = 70

_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\malgun.ttf",
    r"C:\Windows\Fonts\malgunbd.ttf",
    r"C:\Windows\Fonts\gulim.ttc",
    r"C:\Windows\Fonts\batang.ttc",
]
# 제목용 볼드 — 맑은 고딕 Bold 우선.
_BOLD_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\malgunbd.ttf",
    r"C:\Windows\Fonts\malgun.ttf",
    r"C:\Windows\Fonts\gulim.ttc",
    r"C:\Windows\Fonts\batang.ttc",
]


def _load_font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    for fp in (_BOLD_FONT_CANDIDATES if bold else _FONT_CANDIDATES):
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


def _latest_comment(issue) -> Comment | None:
    """가장 최근의 사용자 코멘트(시스템 이력 제외). 없으면 None.

    개발사 송부 PDF 에는 '상태 변경: …' 같은 시스템 코멘트가 아니라 사람이 남긴
    마지막 코멘트(보통 개발사에 전달할 내용)를 싣는다.
    """
    try:
        from . import repository  # 지연 import — 모듈 사이클 방지

        comments = [
            c for c in repository.list_comments(issue.id) if c.kind != "system"
        ]
    except Exception:  # noqa: BLE001
        return None
    if not comments:
        return None
    comments.sort(key=lambda c: c.at)  # at(datetime) 오름차순 → 마지막이 최신
    return comments[-1]


def _draw_text_block(
    page: Image.Image, draw: ImageDraw.ImageDraw, issue
) -> int:
    """제목+설명(한 구역) + 코멘트(구분선 아래 별도 구역)를 그리고 이미지 시작 y 반환.

    2번: 제목은 같은 크기로 더 굵게(볼드), 설명·코멘트는 더 작게, 코멘트 라벨/작성자는
    표시하지 않으며, 제목+설명 구역과 코멘트 구역을 구분선으로 나눈다.
    """
    title_font = _load_font(46, bold=True)  # 제목: 같은 크기 · 볼드
    desc_font = _load_font(25)              # 설명: 더 작게
    comment_font = _load_font(23)           # 코멘트: 더 작게
    content_w = PAGE_W - 2 * MARGIN
    y = MARGIN

    # --- 구역 A: 제목 + 설명 ---
    for line in _wrap(draw, issue.title, title_font, content_w):
        draw.text((MARGIN, y), line, font=title_font, fill=(17, 24, 39))
        y += 58
    y += 10

    desc_limit_y = int(PAGE_H * 0.33)
    for line in _wrap(draw, issue.description or "", desc_font, content_w):
        if y > desc_limit_y:
            draw.text((MARGIN, y), "…", font=desc_font, fill=(30, 30, 30))
            y += 34
            break
        draw.text((MARGIN, y), line, font=desc_font, fill=(31, 41, 55))
        y += 36

    # --- 구역 B: 코멘트 (있으면) — 구분선으로 위 구역과 분리, 라벨/작성자 없음 ---
    last = _latest_comment(issue)
    if last is not None and (last.body or "").strip():
        y += 14
        draw.line(
            [(MARGIN, y), (PAGE_W - MARGIN, y)], fill=(209, 213, 219), width=2
        )
        y += 16
        cmt_limit_y = int(PAGE_H * 0.44)
        for line in _wrap(draw, last.body, comment_font, content_w):
            if y > cmt_limit_y:
                draw.text((MARGIN, y), "…", font=comment_font, fill=(30, 30, 30))
                y += 32
                break
            draw.text((MARGIN, y), line, font=comment_font, fill=(55, 65, 81))
            y += 32

    return y + 18


def _draw_image_grid(
    page: Image.Image,
    draw: ImageDraw.ImageDraw,
    img_paths: list,
    top: int,
    left: int,
    width: int,
    height: int,
) -> None:
    """크기 제각각인 이미지들을 균일한 셀(grid)에 비율 유지로 맞춰 가운데 배치.

    장수에 따라 1·2·3 열로 나누고, 각 이미지는 셀 안에 thumbnail 로 축소되어
    한 장이 과도하게 크거나 작지 않게 보인다.
    """
    n = len(img_paths)
    if n == 0 or height < 140:
        return
    cols = 1 if n == 1 else (2 if n <= 4 else 3)
    rows = (n + cols - 1) // cols
    cell_w = width // cols
    cell_h = max(180, height // rows)
    pad = 14
    caption_font = _load_font(22)

    drawn = 0
    for i, p in enumerate(img_paths):
        r, c = divmod(i, cols)
        cx = left + c * cell_w
        cy = top + r * cell_h
        # 페이지(이미지 영역) 아래로 넘치면 남는 이미지는 생략하고 안내.
        if cy + 140 > top + height:
            break
        try:
            with Image.open(p) as im:
                im = im.convert("RGB")
                im.thumbnail((cell_w - 2 * pad, cell_h - 2 * pad))
                ox = cx + (cell_w - im.width) // 2
                oy = cy + (cell_h - im.height) // 2
                page.paste(im, (ox, oy))
                drawn += 1
        except Exception:  # noqa: BLE001
            continue

    if drawn < n:
        draw.text(
            (left, top + height - 30),
            f"(+{n - drawn}장은 지면 관계로 생략)",
            font=caption_font,
            fill=(107, 114, 128),
        )


def _valid_image_paths(issue) -> list:
    """항목의 첨부 중 표시 가능한 이미지 경로만 (PDF/누락 제외)."""
    item_dir = paths.item_dir(issue.id)
    out = []
    for img_ref in issue.images:
        if str(img_ref.file).lower().endswith(".pdf"):
            continue
        p = item_dir / img_ref.file
        if p.exists():
            out.append(p)
    return out


def _draw_single_image(
    page: Image.Image, path, top: int, left: int, width: int, height: int
) -> None:
    """이미지 1장 — 텍스트 아래 가용 영역에 비율 유지로 '맞게 키워' 가운데 배치 (2번).

    thumbnail 은 축소만 하지만, 여기선 작은 이미지도 업스케일해 화면을 채운다.
    """
    if width < 60 or height < 60:
        return
    pad = 8
    box_w, box_h = width - 2 * pad, height - 2 * pad
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            scale = min(box_w / im.width, box_h / im.height)
            new_w = max(1, int(im.width * scale))
            new_h = max(1, int(im.height * scale))
            im = im.resize((new_w, new_h), Image.LANCZOS)
            ox = left + (width - new_w) // 2
            oy = top + (height - new_h) // 2
            page.paste(im, (ox, oy))
    except Exception:  # noqa: BLE001
        return


def _render_page(issue) -> Image.Image:
    page = Image.new("RGB", (PAGE_W, PAGE_H), "white")
    draw = ImageDraw.Draw(page)

    img_top = _draw_text_block(page, draw, issue)

    content_w = PAGE_W - 2 * MARGIN
    img_area_h = PAGE_H - MARGIN - img_top
    imgs = _valid_image_paths(issue)
    if len(imgs) == 1:
        # 2번: 한 장이면 텍스트를 침범하지 않는 범위에서 화면에 맞게 키운다.
        _draw_single_image(page, imgs[0], img_top, MARGIN, content_w, img_area_h)
    else:
        _draw_image_grid(page, draw, imgs, img_top, MARGIN, content_w, img_area_h)
    return page


def build_issues_pdf(issues: Iterable) -> bytes:
    """Issue 들을 가로(A4 landscape) 페이지당 1개로 그려 PDF bytes 로 반환."""
    pages = [_render_page(iss) for iss in issues]
    if not pages:
        pages = [Image.new("RGB", (PAGE_W, PAGE_H), "white")]
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
