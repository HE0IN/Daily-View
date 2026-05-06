"""Audit 로그 기록 모듈.

docs/02_storage.md 2.6 절의 정의를 그대로 구현한다.

- 항목 단위: ``data/items/{item_id}/item.log`` (item_id 가 주어졌을 때만)
- 전체 통합: ``data/logs/audit.log``

두 곳 모두 JSONL append-only 이며, 라인 손상을 막기 위해
:func:`core.locking.atomic_append_jsonl` 을 사용한다.

라인 구조:
``{"ts": ISO8601, "actor": str, "action": str, "item_id": str|null, "detail": dict|null}``
"""

from __future__ import annotations

import json
from typing import Any

from . import paths
from .clock import now, to_iso
from .locking import atomic_append_jsonl


# ---------------------------------------------------------------------------
# Action 상수
# ---------------------------------------------------------------------------
# 코드 곳곳에서 문자열로 흩어지지 않도록 상수로 노출.

CREATE_ISSUE = "create_issue"
UPDATE_STATUS = "update_status"
UPDATE_ASSIGNEE = "update_assignee"
UPDATE_TAGS = "update_tags"
ADD_COMMENT = "add_comment"
UPLOAD_IMAGE = "upload_image"
CONFIRM_REVIEW = "confirm_review"
ARCHIVE = "archive"
AUTO_ARCHIVE = "auto_archive"


def audit_log(
    actor: str,
    action: str,
    item_id: str | None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Audit 로그를 JSONL 한 줄 append.

    ``item_id`` 가 주어지면 ``items/{id}/item.log`` 와 ``logs/audit.log`` 에 동시 기록.
    주어지지 않은 경우 (예: 시스템 전반 이벤트) 통합 로그에만 기록한다.
    """
    line: dict[str, Any] = {
        "ts": to_iso(now()),
        "actor": actor,
        "action": action,
        "item_id": item_id,
        "detail": detail,
    }

    # 전체 통합 로그
    atomic_append_jsonl(paths.audit_log_path(), line)

    # 항목 단위 로그
    if item_id:
        atomic_append_jsonl(paths.item_log_path(item_id), line)


def tail_audit(n: int = 50) -> list[dict[str, Any]]:
    """전체 audit.log 의 마지막 N 줄을 dict 리스트로 반환.

    파일이 없거나 비어 있으면 빈 리스트 반환. 손상된 라인은 건너뛴다.
    대규모 로그를 가정하지 않는 단순 구현 — 로그가 수만 줄로 커지면
    OS 도구(tail)로 잘라내는 운영 절차를 권장.
    """
    path = paths.audit_log_path()
    if not path.exists():
        return []

    lines: list[str] = []
    with open(path, mode="r", encoding="utf-8") as f:
        # 단순 readlines — 일/월 단위 로테이션을 가정.
        lines = f.readlines()

    tail_lines = lines[-n:] if n > 0 else lines

    result: list[dict[str, Any]] = []
    for raw in tail_lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            result.append(json.loads(raw))
        except json.JSONDecodeError:
            # 손상된 라인은 무시 (운영 중 종료된 쓰기 등)
            continue
    return result


__all__ = [
    "CREATE_ISSUE",
    "UPDATE_STATUS",
    "UPDATE_ASSIGNEE",
    "UPDATE_TAGS",
    "ADD_COMMENT",
    "UPLOAD_IMAGE",
    "CONFIRM_REVIEW",
    "ARCHIVE",
    "AUTO_ARCHIVE",
    "audit_log",
    "tail_audit",
]
