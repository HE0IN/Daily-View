"""전역 사용자 레지스트리 (이름만).

처음 한 번 등록해두면 사이드바에서 radio 로 골라 입장한다. 역할(검토자/개발자)
고정 개념은 폐기되었고, 권한은 항목별 등록자(author)/담당자(assignee)로 결정된다.

- 저장 위치: ``{data_dir}/users.json``
- 구조: ``["이름", ...]``  (구버전 ``[{"name","role"}]`` 도 읽어들임)
- 동시성: 파일 락 + 락 보유 unlocked write.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import paths
from .locking import _write_json_unlocked, file_lock


def _file_path() -> Path:
    return paths.data_dir() / "users.json"


def _lock_path() -> Path:
    return _file_path().with_suffix(".json.lock")


def _load() -> list[str]:
    """이름 목록 로드. 구버전 [{"name","role"}] 형식도 이름만 추출."""
    path = _file_path()
    if not path.exists():
        return []
    try:
        with open(path, mode="r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in data:
        if isinstance(item, dict):
            nm = str(item.get("name", "")).strip()
        else:
            nm = str(item).strip()
        if nm and nm not in seen:
            seen.add(nm)
            out.append(nm)
    return out


def list_users() -> list[str]:
    """등록된 사용자 이름 목록 (이름순)."""
    return sorted(_load())


def add_user(name: str) -> None:
    """사용자 등록. 빈 이름·중복은 무시."""
    name = (name or "").strip()
    if not name:
        return
    with file_lock(_lock_path()):
        data = _load()
        if name not in data:
            data.append(name)
            _write_json_unlocked(_file_path(), data)


def remove_user(name: str) -> None:
    """사용자 제거. 없으면 noop."""
    name = (name or "").strip()
    if not name:
        return
    with file_lock(_lock_path()):
        data = [u for u in _load() if u != name]
        _write_json_unlocked(_file_path(), data)


__all__ = ["list_users", "add_user", "remove_user"]
