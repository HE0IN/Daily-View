"""사용자별 프로젝트 목록 영속화.

사용자가 사이드바에서 새 프로젝트를 추가했을 때 항목이 0 건이라도 다음
방문에 옵션에 보이도록 별도 파일에 저장한다.

- 저장 위치: ``{data_dir}/user_projects.json``
- 구조: ``{user_name: [project_name, ...], ...}``
- 동시성: 파일 락 + 락 보유 unlocked write (재진입 데드락 회피).

``repository.list_projects(participant=name)`` 가 인덱스 기반 추출 결과와
이 파일의 사용자별 프로젝트를 union 해서 반환한다.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import paths
from .locking import _write_json_unlocked, file_lock


def _file_path() -> Path:
    return paths.data_dir() / "user_projects.json"


def _lock_path() -> Path:
    return _file_path().with_suffix(".json.lock")


def _load_all() -> dict[str, list[str]]:
    """전체 user_projects 매핑을 로드. 파일 없으면 빈 dict."""
    path = _file_path()
    if not path.exists():
        return {}
    try:
        with open(path, mode="r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    # 정규화
    result: dict[str, list[str]] = {}
    for k, v in data.items():
        if isinstance(v, list):
            result[str(k)] = [str(x) for x in v if x]
    return result


def _save_all(data: dict[str, list[str]]) -> None:
    """전체 매핑을 atomic 으로 저장. 파일 락."""
    with file_lock(_lock_path()):
        # 락 보유 중 — _write_json_unlocked 사용 (같은 lock 재획득 데드락 회피).
        _write_json_unlocked(_file_path(), data)


def list_user_projects(user: str) -> list[str]:
    """``user`` 의 영속화된 프로젝트 목록 (정렬). 없으면 빈 리스트."""
    if not user:
        return []
    data = _load_all()
    return sorted(set(data.get(user, [])))


def list_all_projects() -> list[str]:
    """모든 사용자가 추가한 프로젝트의 union (정렬). 글로벌 풀 모델용."""
    data = _load_all()
    seen: set[str] = set()
    for projects in data.values():
        for p in projects:
            if p:
                seen.add(p)
    return sorted(seen)


def remove_project_globally(project: str) -> None:
    """모든 사용자의 user_projects 에서 ``project`` 제거. 글로벌 삭제용.

    호출자가 사전 안전 가드 (활성 항목 수 == 0) 를 수행해야 한다.
    """
    project = (project or "").strip()
    if not project:
        return
    with file_lock(_lock_path()):
        data = _load_all()
        changed = False
        for user, projects in list(data.items()):
            new_list = [p for p in projects if p != project]
            if len(new_list) != len(projects):
                changed = True
                if new_list:
                    data[user] = new_list
                else:
                    data.pop(user, None)
        if changed:
            _write_json_unlocked(_file_path(), data)


def add_user_project(user: str, project: str) -> None:
    """``user`` 의 프로젝트 목록에 ``project`` 추가. 락 보유 후 read-modify-write.

    이미 있으면 noop. 빈 입력은 무시.
    """
    user = (user or "").strip()
    project = (project or "").strip()
    if not user or not project:
        return
    with file_lock(_lock_path()):
        data = _load_all()
        existing = data.get(user, [])
        if project not in existing:
            existing.append(project)
            data[user] = existing
            _write_json_unlocked(_file_path(), data)


def remove_user_project(user: str, project: str) -> None:
    """``user`` 의 프로젝트 목록에서 ``project`` 제거. 없으면 noop.

    실제 항목 (Issue) 은 제거하지 않는다 — 호출자가 사전 안전 가드 (활성 항목 수
    체크 등) 를 수행한 후 호출해야 한다.
    """
    user = (user or "").strip()
    project = (project or "").strip()
    if not user or not project:
        return
    with file_lock(_lock_path()):
        data = _load_all()
        existing = data.get(user, [])
        if project in existing:
            existing = [p for p in existing if p != project]
            if existing:
                data[user] = existing
            else:
                data.pop(user, None)
            _write_json_unlocked(_file_path(), data)


__all__ = [
    "list_user_projects",
    "list_all_projects",
    "add_user_project",
    "remove_user_project",
    "remove_project_globally",
]
