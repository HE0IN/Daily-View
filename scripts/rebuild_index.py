"""인덱스 재구축 CLI.

docs/05_setup.md 5.9 트러블슈팅의 "인덱스 손상 후 목록이 안 보임" 대응 도구.

사용:
    python scripts/rebuild_index.py

동작:
1. ``core.index.rebuild_index()`` 호출 → items/ 디렉토리를 전수 순회하여 index.json 갱신
2. ``core.index.verify_index()`` 호출 → 디스크 상태와의 정합성 점검
3. 인덱싱된 항목 수 + 잔존 문제 목록 출력

종료 코드: 0(정상) / 1(rebuild 실패) / 2(rebuild 후에도 문제 잔존)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Windows 콘솔(cp949) 에서 한글 출력 시 UnicodeEncodeError 방지.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

# 프로젝트 루트를 sys.path 에 추가
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core import paths  # noqa: E402
from core.index import rebuild_index, verify_index  # noqa: E402


def main() -> int:
    paths.ensure_data_dirs()

    print(f"[rebuild] 인덱스 재구축 시작")
    print(f"  DATA_DIR : {paths.data_dir()}")
    print(f"  index    : {paths.index_path()}")
    print(f"  items    : {paths.items_dir()}")
    print()

    # 1) rebuild
    started = time.perf_counter()
    try:
        count = rebuild_index()
    except Exception as exc:  # noqa: BLE001
        print(f"[오류] rebuild_index 실패: {exc}")
        return 1
    elapsed = time.perf_counter() - started
    print(f"[rebuild] 완료: {count} 건 인덱싱 ({elapsed:.2f}s)")

    # 2) verify
    print()
    print("[verify] 정합성 점검 시작...")
    ok, problems = verify_index()
    if ok:
        print("  문제 없음. 인덱스가 디스크 상태와 일치합니다.")
        return 0

    print(f"  잔존 문제 {len(problems)}건:")
    for p in problems[:20]:
        print(f"    - {p}")
    if len(problems) > 20:
        print(f"    ... 외 {len(problems) - 20}건")
    return 2


if __name__ == "__main__":
    sys.exit(main())
