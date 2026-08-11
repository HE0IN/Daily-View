"""레거시 ``archived`` 플래그 해제 — 보관돼 있던 항목을 원래 단계로 복귀 (재실행 안전).

배경 — 2026-08-11 이전에는 ``archived`` 하나가 두 가지를 겸했다:
    (1) 사용자가 [삭제] 를 누른 항목
    (2) 완료 후 14일이 지나 자동 보관(auto_archive_closed)된 항목
대시보드 '삭제' 가 archived 전체를 보여줬기 때문에, (2) 가 삭제 목록으로 밀려나
"완료 1건 / 삭제 다수" 로 보였다.

**상태로는 (1)/(2) 를 구분할 수 없다.** 완료된 항목을 다시 열면
(완료 → 등록자검토중 → 반려) archived 는 True 로 남은 채 상태만 바뀌므로,
'담당자검토중인데 자동 보관된' 항목이 실제로 존재한다. 그래서 추측으로 삭제
표시를 하지 않고 **전부 원래 상태 그대로 되살린다**. 진짜 지울 항목은 앱에서
[삭제] 로 다시 표시하면 되고, 그때부터는 삭제 태그(deleted)로 명확히 남는다.

각 항목은 자기 상태에 맞는 섹션으로 자동 복귀한다
(완료 → 완료, 담당자검토중 → 담당자 처리, 확인대기 → 확인요청목록 …).
``updated_at`` 은 건드리지 않는다 (목록 정렬 보존).

앱을 재시작하면 ``app.py`` 부트스트랩이 같은 처리를 자동으로 수행하므로 보통은
이 스크립트를 돌릴 필요가 없다. 재시작 전에 무엇이 어디로 돌아가는지 미리
확인하고 싶을 때 쓴다.

사용법 (반드시 백업 후):
    1) data 폴더 백업:  scripts\\backup.bat
    2) 미리보기:        .venv\\Scripts\\python.exe scripts\\migrate_deleted_tag.py --dry-run
    3) 실제 복구:       .venv\\Scripts\\python.exe scripts\\migrate_deleted_tag.py
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
from core.workflow import STATUS_LABELS_KO  # noqa: E402


def _log(msg: str) -> None:
    print(msg, flush=True)


def _label(status_value: str) -> str:
    """상태값 → 한국어 라벨. 알 수 없는 값은 그대로."""
    for st, ko in STATUS_LABELS_KO.items():
        if st.value == status_value:
            return ko
    return status_value


def preview() -> list[dict]:
    """복구 대상 항목 목록 (아무것도 쓰지 않는다)."""
    out: list[dict] = []
    for entry in index_mod.read_index():
        if not entry.get("archived"):
            continue
        if not entry.get("id"):
            continue
        out.append(
            {
                "id": entry["id"],
                "status": entry.get("status") or "",
                "kind": entry.get("kind") or "dev",
                "title": entry.get("title") or "",
                "deleted": bool(entry.get("deleted")),
            }
        )
    return out


def _print_breakdown(counts: dict[str, int]) -> None:
    for status_value, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        _log(f"    {_label(status_value):<16} {n:>4} 건")


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    _log("[migrate_deleted_tag] start")
    _log(f"[migrate_deleted_tag] data dir = {paths.data_dir()}")

    targets = preview()
    if not targets:
        _log("[migrate_deleted_tag] 대상 없음 — 이미 정리된 상태")
        return

    counts: dict[str, int] = {}
    for t in targets:
        counts[t["status"]] = counts.get(t["status"], 0) + 1

    _log(f"[migrate_deleted_tag] 되살릴 항목 = {len(targets)} 건")
    _log("  상태별 (복귀할 섹션):")
    _print_breakdown(counts)
    _log("  항목:")
    for t in targets:
        _log(f"    [{_label(t['status'])}] {t['title']}  ({t['id']})")

    if dry_run:
        _log("[migrate_deleted_tag] --dry-run — 아무것도 쓰지 않고 종료")
        return

    restored = repository.restore_legacy_archived()
    _log(f"[migrate_deleted_tag] 복구 완료 = {sum(restored.values())} 건")
    _print_breakdown(restored)
    _log("[migrate_deleted_tag] DONE. 앱을 새로고침하세요.")
    _log("[migrate_deleted_tag] 정말 지울 항목은 앱에서 [삭제] 로 다시 표시하세요.")


if __name__ == "__main__":
    main()
