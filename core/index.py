"""목록 캐시(index.json) 관리.

docs/02_storage.md 2.7 절을 따른다. ``items/`` 전체를 매번 순회하지 않도록
요약 캐시를 유지하며, 단건 변경 시마다 동기 갱신한다.

쓰기 함수는 모두 락 → read → modify → :func:`atomic_write_json` 순서로 동작.
락은 :func:`core.locking.atomic_write_json` 가 ``index.json.lock`` 으로 자동 처리.
"""

from __future__ import annotations

import json
from typing import Any

from . import paths
from .clock import now, to_iso
from .locking import _write_json_unlocked, file_lock
from .models import IndexEntry, Issue, Status


_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# 읽기
# ---------------------------------------------------------------------------


def _read_raw_index() -> dict[str, Any]:
    """index.json 전체 dict 를 반환. 파일 없거나 손상 시 빈 구조."""
    path = paths.index_path()
    if not path.exists():
        return {"schema_version": _SCHEMA_VERSION, "updated_at": None, "items": []}

    try:
        with open(path, mode="r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        # 손상이면 빈 구조 반환 — 상위 레이어가 rebuild_index() 호출 결정.
        return {"schema_version": _SCHEMA_VERSION, "updated_at": None, "items": []}

    if not isinstance(data, dict):
        return {"schema_version": _SCHEMA_VERSION, "updated_at": None, "items": []}
    data.setdefault("schema_version", _SCHEMA_VERSION)
    data.setdefault("items", [])
    return data


def read_index() -> list[dict[str, Any]]:
    """index.json 의 ``items`` 리스트만 반환. 파일 없으면 빈 리스트."""
    return list(_read_raw_index().get("items", []))


# ---------------------------------------------------------------------------
# 쓰기
# ---------------------------------------------------------------------------


def _write_index_unlocked(items: list[dict[str, Any]]) -> None:
    """items 리스트로 index.json 전체를 덮어쓴다 (tempfile + os.replace).

    호출자가 이미 인덱스 락을 잡고 있다고 가정. Windows FileLock 의 비재진입성
    때문에, 락 보유 중에는 :func:`atomic_write_json` 대신 본 함수를 사용한다.
    """
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "updated_at": to_iso(now()),
        "items": items,
    }
    _write_json_unlocked(paths.index_path(), payload)


def update_index_entry(
    issue: Issue,
    comments_count: int,
    images_count: int,
) -> None:
    """단일 항목 갱신/추가.

    인덱스 파일 락을 잡고 read → 해당 id 엔트리 교체(없으면 append) →
    atomic_write_json 으로 저장.
    """
    entry = IndexEntry.from_issue(issue, comments_count, images_count)
    entry_dict = entry.model_dump(mode="json")

    # atomic_write_json 가 이미 .lock 을 잡지만, read-modify-write 사이의 race 를
    # 막으려면 명시적으로 한 번 더 잡아야 한다.
    lock_path = paths.index_path().with_suffix(".json.lock")
    with file_lock(lock_path):
        raw = _read_raw_index()
        items: list[dict[str, Any]] = list(raw.get("items", []))

        replaced = False
        for i, existing in enumerate(items):
            if existing.get("id") == issue.id:
                items[i] = entry_dict
                replaced = True
                break
        if not replaced:
            items.append(entry_dict)

        _write_index_unlocked(items)


def remove_index_entry(item_id: str) -> None:
    """주어진 id 엔트리를 인덱스에서 제거. 없으면 무시."""
    lock_path = paths.index_path().with_suffix(".json.lock")
    with file_lock(lock_path):
        raw = _read_raw_index()
        items = [e for e in raw.get("items", []) if e.get("id") != item_id]
        _write_index_unlocked(items)


# ---------------------------------------------------------------------------
# 재구축 / 검증
# ---------------------------------------------------------------------------


def _count_comments_lines(item_id: str) -> int:
    """comments.jsonl 의 비어있지 않은 라인 수."""
    path = paths.item_comments_path(item_id)
    if not path.exists():
        return 0
    count = 0
    with open(path, mode="r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def rebuild_index() -> int:
    """``items/`` 디렉토리를 전수 순회하여 인덱스를 새로 만든다.

    파일이 손상되거나 일관성을 잃었을 때 호출. 반환값은 인덱싱된 항목 수.
    """
    # 동시 갱신 방지 위해 인덱스 락을 명시적으로 잡는다.
    lock_path = paths.index_path().with_suffix(".json.lock")
    items_root = paths.items_dir()

    with file_lock(lock_path):
        items_root.mkdir(parents=True, exist_ok=True)

        new_items: list[dict[str, Any]] = []
        # circular import 회피를 위해 지연 import
        from .images import count_images

        for entry in sorted(items_root.iterdir()):
            if not entry.is_dir():
                continue
            meta_path = entry / "meta.json"
            if not meta_path.exists():
                continue
            try:
                with open(meta_path, mode="r", encoding="utf-8") as f:
                    meta = json.load(f)
                issue = Issue.model_validate(meta)
            except Exception:
                # 손상된 meta 는 스킵 — 운영 중 부분적 손상은 인덱스에서만 빠짐.
                continue

            comments_count = _count_comments_lines(issue.id)
            images_count = count_images(issue.id)
            entry_model = IndexEntry.from_issue(issue, comments_count, images_count)
            new_items.append(entry_model.model_dump(mode="json"))

        _write_index_unlocked(new_items)
        return len(new_items)


def verify_index() -> tuple[bool, list[str]]:
    """인덱스와 디스크 상태의 정합성 점검.

    반환: ``(ok, issues)`` — issues 는 사람이 읽을 수 있는 문제 목록.
    """
    issues: list[str] = []
    items_root = paths.items_dir()

    # 인덱스 측
    index_items = read_index()
    index_ids = {e.get("id") for e in index_items if e.get("id")}

    # 디스크 측
    disk_ids: set[str] = set()
    if items_root.exists():
        for entry in items_root.iterdir():
            if entry.is_dir() and (entry / "meta.json").exists():
                disk_ids.add(entry.name)

    # 인덱스에는 있지만 폴더 없음
    for missing in sorted(index_ids - disk_ids):
        issues.append(f"인덱스에 있으나 폴더 없음: {missing}")
    # 폴더는 있지만 인덱스에 없음
    for extra in sorted(disk_ids - index_ids):
        issues.append(f"폴더는 있으나 인덱스에 없음: {extra}")

    # id 불일치 (meta.json 의 id 가 폴더명과 다른 경우)
    for entry in items_root.iterdir() if items_root.exists() else []:
        if not (entry.is_dir() and (entry / "meta.json").exists()):
            continue
        try:
            with open(entry / "meta.json", mode="r", encoding="utf-8") as f:
                meta = json.load(f)
            meta_id = meta.get("id")
            if meta_id and meta_id != entry.name:
                issues.append(
                    f"id 불일치: 폴더명 '{entry.name}' vs meta.id '{meta_id}'"
                )
        except (json.JSONDecodeError, OSError) as e:
            issues.append(f"meta.json 읽기 실패: {entry.name} ({e})")

    return (len(issues) == 0, issues)


# ---------------------------------------------------------------------------
# 편의: 카운트 조회 헬퍼 (repository 에서 사용)
# ---------------------------------------------------------------------------


def get_counts(item_id: str) -> tuple[int, int]:
    """현재 디스크 상태 기준 (comments_count, images_count)."""
    from .images import count_images

    return _count_comments_lines(item_id), count_images(item_id)


__all__ = [
    "read_index",
    "update_index_entry",
    "remove_index_entry",
    "rebuild_index",
    "verify_index",
    "get_counts",
]
