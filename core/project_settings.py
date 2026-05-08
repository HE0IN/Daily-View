"""프로젝트별 설정 영속화.

프로젝트마다 API 담당자(외부 협력자 등)와 명시적 카테고리 풀(l1/l2/l3)을
관리한다. 항목 인덱스에서 추출하는 카테고리 트리 (``repository.list_categories``)
와는 별개로, 사용자가 *명시적으로* 등록·관리할 수 있는 풀을 제공해
하나도 안 쓰인 카테고리도 옵션으로 노출시킨다.

- 저장 위치: ``{data_dir}/project_settings.json``
- 구조::

    {
        "프로젝트A": {
            "api_assignee": "김외부",
            "categories": {
                "l1": ["로그인", "결제"],
                "l2": ["OAuth", "Stripe"],
                "l3": ["토큰 교환", "환불"]
            }
        }
    }

- 동시성: 파일 락 + 락 보유 unlocked write (재진입 데드락 회피).

API 담당자가 설정된 프로젝트의 항목이 ``api_check`` 상태로 진입하면
:func:`core.repository.update_status` 가 자동으로 담당자를 전환한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import paths
from .locking import _write_json_unlocked, file_lock


# ---------------------------------------------------------------------------
# 경로 / 락
# ---------------------------------------------------------------------------


def _file_path() -> Path:
    return paths.data_dir() / "project_settings.json"


def _lock_path() -> Path:
    return _file_path().with_suffix(".json.lock")


# ---------------------------------------------------------------------------
# 입출력 헬퍼 — user_projects.py 패턴 참고
# ---------------------------------------------------------------------------


_LEVELS: tuple[str, str, str] = ("l1", "l2", "l3")


def _empty_entry() -> dict[str, Any]:
    """초기 빈 엔트리. ``api_assignee`` None, 카테고리 빈 리스트 3 개,
    ``imported_from_index`` False (lazy migration 플래그)."""
    return {
        "api_assignee": None,
        "categories": {lvl: [] for lvl in _LEVELS},
        "imported_from_index": False,
    }


def _normalize_entry(raw: Any) -> dict[str, Any]:
    """단일 프로젝트 엔트리를 안전하게 정규화."""
    entry = _empty_entry()
    if not isinstance(raw, dict):
        return entry

    # api_assignee
    aa = raw.get("api_assignee")
    if isinstance(aa, str):
        s = aa.strip()
        entry["api_assignee"] = s or None

    # categories
    cats = raw.get("categories")
    if isinstance(cats, dict):
        for lvl in _LEVELS:
            seq = cats.get(lvl)
            if isinstance(seq, list):
                entry["categories"][lvl] = [
                    str(x).strip() for x in seq if str(x).strip()
                ]

    # imported_from_index 플래그 (lazy migration)
    entry["imported_from_index"] = bool(raw.get("imported_from_index"))
    return entry


def _load_all() -> dict[str, dict[str, Any]]:
    """전체 프로젝트 설정 매핑을 로드. 파일 없으면 빈 dict."""
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

    result: dict[str, dict[str, Any]] = {}
    for k, v in data.items():
        key = str(k).strip()
        if not key:
            continue
        result[key] = _normalize_entry(v)
    return result


def _save_all(data: dict[str, dict[str, Any]]) -> None:
    """전체 매핑을 atomic 으로 저장. 파일 락.

    호출자가 락을 *보유하지 않은* 상태에서만 사용. 락 안에서는
    :func:`_write_json_unlocked` 를 직접 호출해야 한다 (재진입 데드락 회피).
    """
    with file_lock(_lock_path()):
        _write_json_unlocked(_file_path(), data)


def _get_or_create_entry(
    data: dict[str, dict[str, Any]], project: str
) -> dict[str, Any]:
    """``data`` 에서 ``project`` 엔트리를 가져오되 없으면 생성. 정규화 보장."""
    entry = data.get(project)
    if not isinstance(entry, dict):
        entry = _empty_entry()
        data[project] = entry
        return entry
    # 누락 키 보완
    if "api_assignee" not in entry:
        entry["api_assignee"] = None
    cats = entry.get("categories")
    if not isinstance(cats, dict):
        cats = {lvl: [] for lvl in _LEVELS}
        entry["categories"] = cats
    for lvl in _LEVELS:
        if lvl not in cats or not isinstance(cats[lvl], list):
            cats[lvl] = []
    return entry


def _is_empty_entry(entry: dict[str, Any]) -> bool:
    """엔트리에 의미 있는 데이터가 없으면 True. 키 정리 시 사용."""
    if entry.get("api_assignee"):
        return False
    cats = entry.get("categories") or {}
    for lvl in _LEVELS:
        if cats.get(lvl):
            return False
    return True


# ---------------------------------------------------------------------------
# 공개 API — API 담당자
# ---------------------------------------------------------------------------


def get_api_assignee(project: str) -> str | None:
    """``project`` 의 API 담당자. 미설정/빈 문자열은 None."""
    project = (project or "").strip()
    if not project:
        return None
    data = _load_all()
    entry = data.get(project)
    if not isinstance(entry, dict):
        return None
    aa = entry.get("api_assignee")
    if isinstance(aa, str):
        s = aa.strip()
        return s or None
    return None


def set_api_assignee(project: str, name: str | None) -> None:
    """``project`` 의 API 담당자 설정. ``None`` / 빈 문자열이면 제거.

    제거 후 엔트리가 비면 (카테고리도 없으면) 키 자체를 제거한다.
    """
    project = (project or "").strip()
    if not project:
        return

    if isinstance(name, str):
        cleaned = name.strip()
        normalized: str | None = cleaned or None
    else:
        normalized = name

    with file_lock(_lock_path()):
        data = _load_all()
        entry = _get_or_create_entry(data, project)
        if entry.get("api_assignee") == normalized:
            # 변경 없음 — 빈 엔트리만 정리해서 저장 결정
            if _is_empty_entry(entry) and project in data:
                # 처음부터 비어 있던 keep-alive 케이스: 굳이 변경 없으면 noop
                # 이전 호출 흔적이 없으면 _get_or_create_entry 가 새로 만든 빈 엔트리.
                # 디스크 상태는 이전과 같아야 하므로 키를 제거하고 저장 X.
                # 단, 이미 디스크에 빈 엔트리가 있던 경우는 그대로 둠.
                # 안전하게: 빈 엔트리는 항상 키 제거 후 저장.
                data.pop(project, None)
                _write_json_unlocked(_file_path(), data)
            return

        entry["api_assignee"] = normalized
        if _is_empty_entry(entry):
            data.pop(project, None)
        _write_json_unlocked(_file_path(), data)


# ---------------------------------------------------------------------------
# 공개 API — 카테고리 명시 풀
# ---------------------------------------------------------------------------


def list_project_categories(project: str) -> dict[str, list[str]]:
    """``project`` 의 명시적 카테고리 풀.

    반환값은 항상 ``{"l1": [...], "l2": [...], "l3": [...]}`` 구조이며,
    각 리스트는 정렬된 unique 문자열. 미설정 프로젝트면 빈 리스트들.

    **Lazy migration**: 이 프로젝트가 아직 ``imported_from_index`` 플래그가
    False 면, 인덱스의 기존 항목들에서 사용된 카테고리를 1 회 자동으로
    명시 풀에 추가하고 플래그를 True 로 설정. 사용자가 새 시스템 도입 후
    별도 조작 없이 기존 카테고리가 옵션에 그대로 노출되도록 함. 사용자가
    명시적으로 [×] 삭제한 카테고리는 다음 호출에서 다시 추가되지 않는다
    (플래그가 영속).
    """
    project = (project or "").strip()
    empty = {lvl: [] for lvl in _LEVELS}
    if not project:
        return empty

    _lazy_import_from_index(project)

    data = _load_all()
    entry = data.get(project)
    if not isinstance(entry, dict):
        return empty
    cats = entry.get("categories")
    if not isinstance(cats, dict):
        return empty
    out: dict[str, list[str]] = {}
    for lvl in _LEVELS:
        seq = cats.get(lvl)
        if not isinstance(seq, list):
            out[lvl] = []
            continue
        uniq = sorted({str(x).strip() for x in seq if str(x).strip()})
        out[lvl] = uniq
    return out


def _lazy_import_from_index(project: str) -> None:
    """프로젝트 첫 ``list_project_categories`` 호출 시 1 회 자동 import.

    인덱스 (``repository.list_categories(project=...)``) 의 트리에서
    L1/L2/L3 unique 를 명시 풀에 합치고 ``imported_from_index = True`` 마킹.
    이미 마킹돼 있으면 noop. 사용자가 [×] 삭제한 항목은 플래그가 영속되어
    재추가되지 않음.
    """
    with file_lock(_lock_path()):
        data = _load_all()
        entry = data.get(project)
        if isinstance(entry, dict) and entry.get("imported_from_index"):
            return  # 이미 1 회 import 했음

        # 지연 import — 순환 회피 (project_settings ← repository)
        try:
            from . import repository as repo_mod
            cat_tree = repo_mod.list_categories(project=project)
        except Exception:
            cat_tree = {}

        if not isinstance(entry, dict):
            entry = _empty_entry()
        cats = entry.setdefault("categories", {lvl: [] for lvl in _LEVELS})

        def _push(level: str, name: str) -> None:
            cleaned = (name or "").strip()
            if not cleaned:
                return
            current = cats.get(level)
            if not isinstance(current, list):
                current = []
            if cleaned not in current:
                current.append(cleaned)
            cats[level] = current

        for l1_name, l2_map in (cat_tree or {}).items():
            _push("l1", l1_name)
            for l2_name, l3_set in (l2_map or {}).items():
                _push("l2", l2_name)
                for l3_name in l3_set or []:
                    _push("l3", l3_name)

        entry["imported_from_index"] = True
        data[project] = entry
        _write_json_unlocked(_file_path(), data)


def add_project_category(
    project: str,
    *,
    l1: str | None = None,
    l2: str | None = None,
    l3: str | None = None,
) -> None:
    """``project`` 의 카테고리 풀에 라벨 추가.

    3 단계 중 일부만 줘도 OK. 빈 문자열 / 공백만은 무시. 이미 있으면 noop.
    """
    project = (project or "").strip()
    if not project:
        return

    additions: dict[str, str] = {}
    for lvl, val in (("l1", l1), ("l2", l2), ("l3", l3)):
        if isinstance(val, str):
            s = val.strip()
            if s:
                additions[lvl] = s
    if not additions:
        return

    with file_lock(_lock_path()):
        data = _load_all()
        entry = _get_or_create_entry(data, project)
        cats = entry["categories"]
        changed = False
        for lvl, label in additions.items():
            existing = cats.get(lvl) or []
            if label not in existing:
                existing.append(label)
                cats[lvl] = existing
                changed = True
        if changed:
            _write_json_unlocked(_file_path(), data)
        elif _is_empty_entry(entry) and project in data and entry is data.get(project):
            # _get_or_create_entry 가 빈 엔트리를 만들었지만 추가도 없었던 경우 → 키 제거
            data.pop(project, None)
            _write_json_unlocked(_file_path(), data)


def remove_project_category(
    project: str,
    *,
    l1: str | None = None,
    l2: str | None = None,
    l3: str | None = None,
) -> None:
    """``project`` 의 카테고리 풀에서 라벨 제거. 없으면 noop."""
    project = (project or "").strip()
    if not project:
        return

    removals: dict[str, str] = {}
    for lvl, val in (("l1", l1), ("l2", l2), ("l3", l3)):
        if isinstance(val, str):
            s = val.strip()
            if s:
                removals[lvl] = s
    if not removals:
        return

    with file_lock(_lock_path()):
        data = _load_all()
        entry = data.get(project)
        if not isinstance(entry, dict):
            return
        cats = entry.get("categories")
        if not isinstance(cats, dict):
            return
        changed = False
        for lvl, label in removals.items():
            existing = cats.get(lvl) or []
            if label in existing:
                cats[lvl] = [x for x in existing if x != label]
                changed = True
        if not changed:
            return
        # 빈 엔트리는 키 제거
        if _is_empty_entry(entry):
            data.pop(project, None)
        _write_json_unlocked(_file_path(), data)


# ---------------------------------------------------------------------------
# 공개 API — 프로젝트 자체 정리
# ---------------------------------------------------------------------------


def remove_project_settings(project: str) -> None:
    """``project`` 의 모든 설정(api_assignee + categories)을 제거.

    프로젝트를 글로벌하게 삭제할 때 호출. 키가 없으면 noop.
    """
    project = (project or "").strip()
    if not project:
        return
    with file_lock(_lock_path()):
        data = _load_all()
        if project in data:
            data.pop(project, None)
            _write_json_unlocked(_file_path(), data)


__all__ = [
    "get_api_assignee",
    "set_api_assignee",
    "list_project_categories",
    "add_project_category",
    "remove_project_category",
    "remove_project_settings",
]
