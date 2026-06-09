"""옛 상태 체계 → 새 등록자/담당자 체계 마이그레이션 (일회성).

옛 11 상태(요청중/개발검토/개발중/…)를 새 10 상태(담당자확인요청/…)로 치환한다.
각 ``meta.json`` 의 ``status`` 와 ``status_history[].status`` 를 매핑대로 바꾸고,
끝에 인덱스를 재구축한다.

raw JSON 으로 처리 — 옛 enum 값은 새 pydantic 모델에 없으므로 model_validate 를
쓰지 않는다.

사용법 (반드시 백업 후):
    1) data 폴더 백업:  scripts\\backup.bat
    2) .venv\\Scripts\\python.exe scripts\\migrate_v2.py
    3) (자동) 인덱스 재구축

매핑:
    requested      -> assignee_request      (담당자확인요청)
    dev_review     -> assignee_reviewing    (담당자검토중)
    in_progress    -> assignee_developing   (담당자신규개발중)
    modifying      -> assignee_fixing       (담당자코드수정중)
    api_check      -> vendor_request        (개발사확인중)
    vendor_dev     -> vendor_reply          (개발사회신확인중)
    vendor_fix     -> vendor_reply          (개발사회신확인중)
    reviewing      -> author_reviewing      (등록자검토중)
    needs_recheck  -> assignee_request      (담당자확인요청; 반려 재시작)
    rejected       -> assignee_request      (담당자확인요청; 반려 재시작)
    closed         -> closed                (완료)
    done(레거시)   -> closed                (완료)
    reopened(레거시)-> assignee_request     (담당자확인요청)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 프로젝트 루트를 import 경로에 추가 (scripts/ 하위에서 실행될 때)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows 콘솔(CP949)에서도 print 가 인코딩 에러로 막히지 않도록 UTF-8 강제.
# (이게 없으면 한글/기호 출력 시 UnicodeEncodeError 로 멈추거나 아무것도 안 보임)
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

from core import paths  # noqa: E402

STATUS_MAP: dict[str, str] = {
    "requested": "assignee_request",
    "dev_review": "assignee_reviewing",
    "in_progress": "assignee_developing",
    "modifying": "assignee_fixing",
    "api_check": "vendor_request",
    "vendor_dev": "vendor_reply",
    "vendor_fix": "vendor_reply",
    "reviewing": "author_reviewing",
    "needs_recheck": "assignee_request",
    "rejected": "assignee_request",
    "closed": "closed",
    "done": "closed",
    "reopened": "assignee_request",
}

# 이미 새 체계인 값들 — 만나면 그대로 둔다 (재실행 안전).
NEW_STATUSES = {
    "assignee_request",
    "assignee_reviewing",
    "assignee_reviewed",
    "assignee_developing",
    "assignee_fixing",
    "vendor_request",
    "vendor_reply",
    "author_request",
    "author_reviewing",
    "closed",
}


def _log(msg: str) -> None:
    """줄 단위 즉시 출력 (버퍼링으로 '멈춘 것처럼' 보이는 것 방지)."""
    print(msg, flush=True)


def _map_status(value: object) -> tuple[str | None, bool]:
    """(새 값, 변경여부) 반환. 이미 새 값이거나 알 수 없으면 (원본, False)."""
    if not isinstance(value, str):
        return value, False  # type: ignore[return-value]
    if value in NEW_STATUSES:
        return value, False
    if value in STATUS_MAP:
        return STATUS_MAP[value], True
    return value, False  # 알 수 없는 값 — 보존


def migrate_meta(meta_path: Path) -> bool:
    """meta.json 한 건을 마이그레이션. 변경 시 atomic write 후 True."""
    try:
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _log(f"  [WARN] read failed {meta_path}: {exc}")
        return False

    changed = False

    new_status, did = _map_status(raw.get("status"))
    if did:
        raw["status"] = new_status
        changed = True

    for ev in raw.get("status_history", []):
        if not isinstance(ev, dict):
            continue
        mapped, did_ev = _map_status(ev.get("status"))
        if did_ev:
            ev["status"] = mapped
            changed = True

    if changed:
        tmp = meta_path.with_suffix(".json.migtmp")
        tmp.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(meta_path)
    return changed


def main() -> None:
    _log("[migrate_v2] start")
    items_dir = paths.items_dir()
    _log(f"[migrate_v2] items dir = {items_dir}")
    if not items_dir.exists():
        _log("[migrate_v2] items dir not found - nothing to migrate")
        return

    metas = sorted(items_dir.glob("*/meta.json"))
    _log(f"[migrate_v2] target items = {len(metas)}")

    migrated = 0
    for mp in metas:
        if migrate_meta(mp):
            migrated += 1
            _log(f"  [OK] {mp.parent.name}")

    _log(f"[migrate_v2] status migrated = {migrated}/{len(metas)}")

    _log("[migrate_v2] rebuilding index ...")
    from core.index import rebuild_index

    n = rebuild_index()
    _log(f"[migrate_v2] index rebuilt = {n}")
    _log("[migrate_v2] DONE. Restart the app.")


if __name__ == "__main__":
    main()
