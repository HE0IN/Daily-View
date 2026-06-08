"""전역 사용자 레지스트리 (이름 + 역할).

처음 한 번 등록해두면 이후 사이드바에서 radio 로 선택해 로그인한다.
역할(검토자/개발자)은 등록 시점에 함께 저장된다.

- 저장 위치: ``{data_dir}/users.json``
- 구조: ``[{"name": str, "role": "reviewer"|"developer"}, ...]``
- 동시성: 파일 락 + 락 보유 unlocked write (재진입 데드락 회피).
"""

from __future__ import annotations

import json
from pathlib import Path

from . import paths
from .locking import _write_json_unlocked, file_lock

_VALID_ROLES = ("reviewer", "developer")


def _file_path() -> Path:
    return paths.data_dir() / "users.json"


def _lock_path() -> Path:
    return _file_path().with_suffix(".json.lock")


def _normalize_role(role: object) -> str:
    return role if role in _VALID_ROLES else "reviewer"


def _load() -> list[dict]:
    """전체 사용자 목록 로드. 파일 없거나 손상 시 빈 리스트."""
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
    out: list[dict] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        nm = str(item.get("name", "")).strip()
        if not nm or nm in seen:
            continue
        seen.add(nm)
        out.append({"name": nm, "role": _normalize_role(item.get("role"))})
    return out


def list_users() -> list[dict]:
    """등록된 사용자 목록 (이름순). 각 원소 ``{"name", "role"}``."""
    return sorted(_load(), key=lambda u: u["name"])


def add_user(name: str, role: str) -> None:
    """사용자 등록. 이름이 이미 있으면 역할만 갱신. 빈 이름은 무시."""
    name = (name or "").strip()
    if not name:
        return
    role = _normalize_role(role)
    with file_lock(_lock_path()):
        data = _load()
        for u in data:
            if u["name"] == name:
                u["role"] = role
                break
        else:
            data.append({"name": name, "role": role})
        _write_json_unlocked(_file_path(), data)


def remove_user(name: str) -> None:
    """사용자 제거. 없으면 noop."""
    name = (name or "").strip()
    if not name:
        return
    with file_lock(_lock_path()):
        data = [u for u in _load() if u["name"] != name]
        _write_json_unlocked(_file_path(), data)


def get_role(name: str) -> str | None:
    """등록된 사용자의 역할. 없으면 None."""
    name = (name or "").strip()
    for u in _load():
        if u["name"] == name:
            return u["role"]
    return None


__all__ = ["list_users", "add_user", "remove_user", "get_role"]
