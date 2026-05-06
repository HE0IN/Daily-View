"""이미지 저장 + 슬러그 + 한도 테스트."""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from core import images as images_mod
from core import paths, repository
from core.images import (
    ALLOWED_EXT,
    MAX_FILE_MB,
    MAX_IMAGES_PER_ITEM,
    save_image_bytes,
    slugify,
)
from core.models import Role


# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------


def test_slugify_korean() -> None:
    """한글 파일명은 그대로 보존되며 공백/구두점은 ``_``."""
    # 입력은 stem (확장자 제거된 이름) 이라고 가정
    assert slugify("한글 파일명") == "한글_파일명"


def test_slugify_special_chars() -> None:
    """슬래시/콜론/공백/기타 특수문자는 ``_`` 로 치환되고 연속은 압축."""
    assert slugify("foo/bar:baz qux") == "foo_bar_baz_qux"
    assert slugify("a   b") == "a_b"  # 연속 _ 압축
    assert slugify("a---b") == "a---b"  # 하이픈은 보존
    # 양 끝 _ 제거
    assert slugify("__foo__") == "foo"


def test_slugify_empty_or_all_special() -> None:
    """빈 문자열 또는 모든 문자가 특수문자 → 'image'."""
    assert slugify("") == "image"
    assert slugify("!@#$%") == "image"
    assert slugify("///") == "image"


def test_slugify_alphanumeric_passthrough() -> None:
    """영문/숫자는 그대로 통과."""
    assert slugify("hello123") == "hello123"


# ---------------------------------------------------------------------------
# save_image_bytes
# ---------------------------------------------------------------------------


def _make_png_bytes(size: tuple[int, int] = (1, 1)) -> bytes:
    """1x1 PNG 바이트 생성 (PIL 사용)."""
    img = Image.new("RGB", size, color=(128, 64, 200))
    buf = BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def test_save_image_bytes_creates_file_and_thumbnail(tmp_path: Path) -> None:
    """원본 + .thumb.jpg 둘 다 디스크에 존재. ImageRef 메타 정확."""
    # save_image_bytes 는 dest_dir.parent 를 'item_root' 로 간주하여 상대경로를 만든다.
    item_root = tmp_path / "items" / "test-id"
    dest = item_root / "images"

    data = _make_png_bytes((10, 10))
    ref = save_image_bytes(data, "테스트.png", dest, seq=1)

    # 파일 존재
    files = sorted(p.name for p in dest.iterdir())
    # 원본 + 썸네일 두 개
    assert len(files) == 2, f"파일 개수 비정상: {files}"
    assert any(f.endswith(".png") for f in files), f"원본 png 없음: {files}"
    assert any(f.endswith(".thumb.jpg") for f in files), f"썸네일 없음: {files}"

    # 파일명 패턴: 001_<slug>.png
    src_files = [f for f in files if f.endswith(".png") and not f.endswith(".thumb.png")]
    assert src_files[0].startswith("001_")

    # ImageRef 메타
    expected_sha = hashlib.sha256(data).hexdigest()
    assert ref.sha256 == expected_sha
    assert ref.size_bytes == len(data)
    assert ref.file.startswith("images/")
    assert ref.thumb is not None and ref.thumb.startswith("images/")
    assert ref.thumb.endswith(".thumb.jpg")
    assert ref.uploaded_at.tzinfo is not None, "uploaded_at 가 timezone-naive"


def test_save_image_bytes_size_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MAX_FILE_MB 초과 시 ValueError."""
    # 모듈 상수를 1MB 로 임시 패치 (env 변수는 import 시점에 읽혀서 패치 무의미)
    monkeypatch.setattr(images_mod, "MAX_FILE_MB", 1)

    big_data = b"\x00" * (2 * 1024 * 1024)  # 2 MB

    item_root = tmp_path / "items" / "test-id"
    dest = item_root / "images"

    with pytest.raises(ValueError, match="크기"):
        save_image_bytes(big_data, "huge.png", dest, seq=1)


def test_save_image_bytes_extension_limit(tmp_path: Path) -> None:
    """허용되지 않는 확장자 → ValueError."""
    item_root = tmp_path / "items" / "test-id"
    dest = item_root / "images"
    data = _make_png_bytes()

    with pytest.raises(ValueError, match="확장자"):
        save_image_bytes(data, "evil.bmp", dest, seq=1)


def test_save_image_bytes_uppercase_extension(tmp_path: Path) -> None:
    """대문자 확장자도 정상 처리 (소문자로 변환)."""
    item_root = tmp_path / "items" / "test-id"
    dest = item_root / "images"
    data = _make_png_bytes()

    ref = save_image_bytes(data, "CAPS.PNG", dest, seq=1)
    assert ref.file.endswith(".png"), f"확장자가 소문자로 정규화되지 않음: {ref.file}"


def test_allowed_extensions_set() -> None:
    """ALLOWED_EXT 가 docs 에 명시된 5종을 포함."""
    assert {".png", ".jpg", ".jpeg", ".gif", ".webp"} <= ALLOWED_EXT


# ---------------------------------------------------------------------------
# repository 통합: 이미지 한도
# ---------------------------------------------------------------------------


def test_repository_image_count_limit(
    temp_data_dir: Path,
    sample_issue_kwargs: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MAX_IMAGES_PER_ITEM 도달 후 추가 시도 → ValueError."""
    # 한도를 작게 패치 — 모듈 두 곳 모두 (repository 가 import 시 바인딩한 값까지)
    monkeypatch.setattr(images_mod, "MAX_IMAGES_PER_ITEM", 2)
    monkeypatch.setattr(repository, "MAX_IMAGES_PER_ITEM", 2)

    issue = repository.create_issue(**sample_issue_kwargs)
    data = _make_png_bytes()

    repository.add_image_from_bytes(issue.id, data, "a.png", actor="rev")
    repository.add_image_from_bytes(issue.id, data, "b.png", actor="rev")

    with pytest.raises(ValueError, match="이미지 개수"):
        repository.add_image_from_bytes(issue.id, data, "c.png", actor="rev")

    # 디스크에는 2장만 (count_images 는 .thumb.jpg 제외)
    assert images_mod.count_images(issue.id) == 2


def test_repository_image_updates_meta_and_index(
    temp_data_dir: Path, sample_issue_kwargs: dict
) -> None:
    """이미지 추가 후 meta.images 와 index.images_count 둘 다 갱신."""
    from core import index as index_mod

    issue = repository.create_issue(**sample_issue_kwargs)
    data = _make_png_bytes()

    ref = repository.add_image_from_bytes(issue.id, data, "shot.png", actor="rev")

    refreshed = repository.get_issue(issue.id)
    assert len(refreshed.images) == 1
    assert refreshed.images[0].sha256 == ref.sha256

    # 인덱스
    raw = index_mod.read_index()
    entry = next(e for e in raw if e["id"] == issue.id)
    assert entry["images_count"] == 1
