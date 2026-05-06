"""이미지 저장 + 썸네일 생성 모듈.

docs/02_storage.md 2.4 절을 따른다.

- 원본: ``items/{id}/images/{NNN}_{slug}.{ext}``
- 썸네일: ``items/{id}/images/{NNN}_{slug}.thumb.jpg`` (가로 200px, EXIF 회전 보정)
- 검증: 파일 크기 ≤ MAX_FILE_MB, 확장자 ALLOWED_EXT
- 메타: sha256, size_bytes 를 함께 ImageRef 로 반환
"""

from __future__ import annotations

import hashlib
import io
import os
import re
from pathlib import Path

from PIL import Image, ImageOps

from . import paths
from .clock import now
from .models import ImageRef


# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

MAX_FILE_MB: int = int(os.environ.get("MAX_UPLOAD_MB", "10"))
MAX_IMAGES_PER_ITEM: int = int(os.environ.get("MAX_IMAGES_PER_ITEM", "20"))
ALLOWED_EXT: set[str] = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

# 썸네일은 카드/목록의 작은 영역에 보일 뿐 아니라 모바일/HiDPI 디스플레이에서
# 2배 픽셀로 렌더되므로 800px 정도가 화질·용량 균형이 좋다.
# (200px 였을 때는 카드 폭으로 늘리면 흐릿하게 보였음.)
_THUMB_MAX_WIDTH: int = 800
_THUMB_QUALITY: int = 85


# ---------------------------------------------------------------------------
# 슬러그
# ---------------------------------------------------------------------------


def slugify(text: str) -> str:
    """파일명용 슬러그. 한글은 그대로 보존하되 공백·구두점은 ``_`` 로 치환.

    빈 문자열 또는 변환 결과가 비면 ``"image"`` 반환.
    """
    if not text:
        return "image"

    # \w 는 re.UNICODE 기본 적용 → 한글이 보존됨. 슬래시/공백/특수문자만 _ 로.
    cleaned = re.sub(r"[^\w\-]", "_", text, flags=re.UNICODE)
    # 연속 _ 압축
    cleaned = re.sub(r"_+", "_", cleaned)
    # 양쪽 _ 제거
    cleaned = cleaned.strip("_")
    return cleaned or "image"


# ---------------------------------------------------------------------------
# 핵심 저장 함수
# ---------------------------------------------------------------------------


def _validate(data: bytes, original_filename: str) -> str:
    """크기/확장자 검증. 통과한 확장자(소문자, 점 포함)를 반환."""
    size_mb = len(data) / (1024 * 1024)
    if size_mb > MAX_FILE_MB:
        raise ValueError(
            f"이미지 크기/형식 오류: 파일 크기 {size_mb:.1f}MB 가 한도({MAX_FILE_MB}MB) 초과"
        )

    ext = Path(original_filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise ValueError(
            f"이미지 크기/형식 오류: 허용되지 않는 확장자 '{ext}' "
            f"(허용: {sorted(ALLOWED_EXT)})"
        )
    return ext


def save_image_bytes(
    data: bytes,
    original_filename: str,
    dest_dir: Path,
    seq: int,
) -> ImageRef:
    """원본 바이트를 받아 저장하고 썸네일까지 생성.

    호출자(=repository)가 ``seq`` 와 ``dest_dir`` 을 결정한다. 본 함수는
    이미지 처리 로직만 담당.
    """
    ext = _validate(data, original_filename)
    slug = slugify(Path(original_filename).stem)

    dest_dir.mkdir(parents=True, exist_ok=True)

    # 경로 구성
    base = dest_dir / f"{seq:03d}_{slug}"
    src_path = base.with_suffix(ext)
    thumb_path = base.with_suffix(".thumb.jpg")

    # 원본 저장
    src_path.write_bytes(data)

    # 썸네일 생성 (EXIF 회전 보정 + 가로 200px)
    try:
        with Image.open(io.BytesIO(data)) as img:
            img = ImageOps.exif_transpose(img)
            img.thumbnail((_THUMB_MAX_WIDTH, _THUMB_MAX_WIDTH * 10))
            img.convert("RGB").save(thumb_path, "JPEG", quality=_THUMB_QUALITY)
    except Exception:
        # 썸네일 실패해도 원본은 남도록 — 다만 일관성 위해 원본도 롤백.
        try:
            src_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    sha256 = hashlib.sha256(data).hexdigest()

    # 항목 디렉토리에 대한 상대경로로 기록 (meta.json 휴대성 ↑)
    item_root = dest_dir.parent  # items/{id}/
    rel_src = src_path.relative_to(item_root).as_posix()
    rel_thumb = thumb_path.relative_to(item_root).as_posix()

    return ImageRef(
        file=rel_src,
        thumb=rel_thumb,
        uploaded_at=now(),
        sha256=sha256,
        size_bytes=len(data),
    )


def save_pil_image(
    img: Image.Image,
    original_filename: str,
    dest_dir: Path,
    seq: int,
) -> ImageRef:
    """PIL.Image 객체를 PNG 로 직렬화 후 :func:`save_image_bytes` 로 저장.

    streamlit-paste-button 등 클립보드 입력 경로에서 사용.
    """
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    data = buffer.getvalue()

    # original_filename 의 확장자가 ALLOWED_EXT 가 아니면 .png 로 바꿔 검증 통과시킴.
    stem = Path(original_filename).stem or "pasted"
    safe_filename = f"{stem}.png"
    return save_image_bytes(data, safe_filename, dest_dir, seq)


# ---------------------------------------------------------------------------
# 카운트
# ---------------------------------------------------------------------------


def count_images(item_id: str) -> int:
    """items/{id}/images/ 의 비썸네일 파일 수.

    썸네일은 ``.thumb.jpg`` 패턴이므로 그것을 제외한다. 디렉토리 없으면 0.
    """
    images_dir = paths.item_images_dir(item_id)
    if not images_dir.exists():
        return 0

    count = 0
    for entry in images_dir.iterdir():
        if not entry.is_file():
            continue
        if entry.name.endswith(".thumb.jpg"):
            continue
        count += 1
    return count


__all__ = [
    "MAX_FILE_MB",
    "MAX_IMAGES_PER_ITEM",
    "ALLOWED_EXT",
    "slugify",
    "save_image_bytes",
    "save_pil_image",
    "count_images",
]
