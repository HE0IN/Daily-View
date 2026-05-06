"""기존 이미지의 썸네일을 현재 ``core.images._THUMB_MAX_WIDTH`` 로 재생성한다.

사용 예:
    # 폭이 현재 설정보다 작은 썸네일만 재생성
    python scripts/regen_thumbs.py

    # 모든 썸네일 강제 재생성
    python scripts/regen_thumbs.py --force

    # 어떤 썸네일이 갱신될지 미리 보기 (실제 변경 X)
    python scripts/regen_thumbs.py --dry-run

썸네일 해상도 정책 (``core/images.py`` 의 ``_THUMB_MAX_WIDTH``) 을 올린 직후
1회 실행 권장.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path 에 추가 (스크립트 단독 실행 지원)
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 콘솔 한글 출력 안전화 (Windows cp949 방지)
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

from PIL import Image, ImageOps  # noqa: E402

from core import paths  # noqa: E402
from core.images import _THUMB_MAX_WIDTH, _THUMB_QUALITY  # noqa: E402


def _thumb_width(thumb_path: Path) -> int | None:
    """썸네일 이미지의 가로 픽셀. 열기 실패하면 ``None``."""
    try:
        with Image.open(thumb_path) as img:
            return img.size[0]
    except Exception:
        return None


def _regen_one(src: Path, thumb: Path) -> bool:
    """원본 ``src`` 로부터 썸네일 ``thumb`` 재생성. 성공 시 True."""
    try:
        with Image.open(src) as img:
            corrected = ImageOps.exif_transpose(img)
            corrected.thumbnail((_THUMB_MAX_WIDTH, _THUMB_MAX_WIDTH))
            corrected.convert("RGB").save(
                thumb, "JPEG", quality=_THUMB_QUALITY, optimize=True
            )
        return True
    except Exception as exc:
        print(f"  실패: {src.name} — {exc}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="현재 폭과 무관하게 모든 썸네일 강제 재생성",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 변경하지 않고 대상만 출력",
    )
    args = parser.parse_args()

    items_root = paths.items_dir()
    if not items_root.exists():
        print(f"항목 디렉토리 없음: {items_root}")
        return 0

    print(f"대상 디렉토리: {items_root}")
    print(f"목표 썸네일 폭: {_THUMB_MAX_WIDTH}px (quality={_THUMB_QUALITY})")
    print(f"모드: {'force (모두 재생성)' if args.force else '폭 미달만 재생성'}"
          f"{' [DRY RUN]' if args.dry_run else ''}")
    print("---")

    examined = 0
    regenerated = 0
    skipped = 0

    for item_dir in sorted(items_root.iterdir()):
        if not item_dir.is_dir():
            continue
        images_dir = item_dir / "images"
        if not images_dir.exists():
            continue

        for thumb in sorted(images_dir.glob("*.thumb.jpg")):
            examined += 1
            # 원본 추정: ``001_foo.thumb.jpg`` → ``001_foo.{원본 ext}``
            stem = thumb.name[: -len(".thumb.jpg")]
            candidates = [
                p for p in images_dir.iterdir()
                if p.is_file() and p.stem == stem and p != thumb
            ]
            if not candidates:
                print(f"  원본 없음 → 스킵: {item_dir.name}/{thumb.name}")
                skipped += 1
                continue
            src = candidates[0]

            if not args.force:
                cur_w = _thumb_width(thumb)
                if cur_w is not None and cur_w >= _THUMB_MAX_WIDTH:
                    skipped += 1
                    continue

            print(f"  재생성: {item_dir.name}/{src.name} → {thumb.name}")
            if not args.dry_run:
                if _regen_one(src, thumb):
                    regenerated += 1
            else:
                regenerated += 1

    print("---")
    print(f"검사: {examined}개 / 재생성: {regenerated}개 / 스킵: {skipped}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
