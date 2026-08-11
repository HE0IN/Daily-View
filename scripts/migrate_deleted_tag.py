"""레거시 ``archived`` 플래그 → 삭제 태그(``deleted``) 이관 (재실행 안전).

배경 — 2026-08-11 이전에는 ``archived`` 하나가 두 가지를 겸했다:
    (1) 사용자가 [삭제] 를 누른 항목
    (2) 완료 후 14일이 지나 자동 보관(auto_archive_closed)된 항목
대시보드 '삭제' 가 archived 전체를 보여줬기 때문에, (2) 의 완료 항목들이
'삭제' 목록으로 밀려나 "완료 1건 / 삭제 다수" 로 보였다.

이관 규칙:
    archived + 완료(closed)  → 자동 보관된 완료 항목. 플래그만 내려 완료로 복귀
    archived + 완료 아님      → 사람이 삭제한 항목. deleted = True 로 이관

``updated_at`` 은 건드리지 않는다 (목록 정렬 보존).

앱을 재시작하면 ``app.py`` 부트스트랩이 같은 처리를 자동으로 수행하므로 보통은
이 스크립트를 돌릴 필요가 없다. 재시작 전에 결과를 미리 확인하고 싶을 때 쓴다.

사용법 (반드시 백업 후):
    1) data 폴더 백업:  scripts\\backup.bat
    2) 미리보기:        .venv\\Scripts\\python.exe scripts\\migrate_deleted_tag.py --dry-run
    3) 실제 이관:       .venv\\Scripts\\python.exe scripts\\migrate_deleted_tag.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# 프로젝트 루트를 import 경로에 추가 (scripts/ 하위에서 실행될 때)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows 콘솔(CP949)에서도 한글 출력이 막히지 않도록 UTF-8 강제.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

from core import index as index_mod  # noqa: E402
from core import paths, repository  # noqa: E402
from core.models import Status  # noqa: E402


def _log(msg: str) -> None:
    print(msg, flush=True)


def preview() -> tuple[list[str], list[str]]:
    """(완료로 되돌릴 id 들, 삭제 태그를 붙일 id 들) — 아무것도 쓰지 않는다."""
    to_restore: list[str] = []
    to_delete: list[str] = []
    for entry in index_mod.read_index():
        if not entry.get("archived"):
            continue
        item_id = entry.get("id")
        if not item_id:
            continue
        if entry.get("status") == Status.closed.value:
            to_restore.append(item_id)
        else:
            to_delete.append(item_id)
    return to_restore, to_delete


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    _log("[migrate_deleted_tag] start")
    _log(f"[migrate_deleted_tag] data dir = {paths.data_dir()}")

    restore_ids, delete_ids = preview()
    _log(
        f"[migrate_deleted_tag] 대상: 완료로 복귀 {len(restore_ids)}건 / "
        f"삭제 태그 {len(delete_ids)}건"
    )
    for iid in restore_ids:
        _log(f"  [완료] {iid}")
    for iid in delete_ids:
        _log(f"  [삭제] {iid}")

    if dry_run:
        _log("[migrate_deleted_tag] --dry-run — 아무것도 쓰지 않고 종료")
        return

    if not restore_ids and not delete_ids:
        _log("[migrate_deleted_tag] 대상 없음 — 이미 정리된 상태")
        return

    restored, tagged = repository.migrate_archived_to_deleted()
    _log(f"[migrate_deleted_tag] 완료로 복귀 = {restored}건")
    _log(f"[migrate_deleted_tag] 삭제 태그 부착 = {tagged}건")
    _log("[migrate_deleted_tag] DONE. 앱을 새로고침하세요.")


if __name__ == "__main__":
    main()
