"""list_issues 응답 시간 측정.

docs/06_implementation_plan.md 6.4 의 "1년치 2,500건에서 목록 페이지 응답시간 1초 이내"
검증을 코드로 자동화한 부분.

사용:
    python scripts/perf_check.py

먼저 ``scripts/seed_dummy.py --count 2500`` 등으로 데이터를 채워두고 실행한다.
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

from core import paths, repository  # noqa: E402
from core.index import read_index  # noqa: E402


_SLA_SECONDS = 1.0  # 6.4 항목: 1초 이내


def _measure(label: str, fn) -> tuple[object, float]:
    """fn 실행 시간 측정. 반환 (결과, 초)."""
    t0 = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - t0
    print(f"  {label:35s} → {elapsed * 1000:7.1f} ms")
    return result, elapsed


def main() -> int:
    paths.ensure_data_dirs()

    print("성능 측정 시작")
    print(f"  DATA_DIR: {paths.data_dir()}")
    print()

    raw = read_index()
    print(f"인덱스 항목 수: {len(raw)}")
    print()

    print("측정 항목 (각 1회):")
    items_all, e_all = _measure(
        "list_issues() 전체",
        lambda: repository.list_issues(),
    )
    items_active, e_active = _measure(
        "list_issues(include_closed=False)",
        lambda: repository.list_issues(include_closed=False),
    )
    items_high, e_high = _measure(
        "list_issues(urgency='high')",
        lambda: repository.list_issues(urgency="high"),
    )
    items_search, e_search = _measure(
        "list_issues(search='로그인')",
        lambda: repository.list_issues(search="로그인"),
    )

    print()
    print("결과 카운트:")
    print(f"  전체 활성+종료    : {len(items_all)}")
    print(f"  활성만             : {len(items_active)}")
    print(f"  긴급도 high        : {len(items_high)}")
    print(f"  검색 '로그인'      : {len(items_search)}")

    print()
    longest = max(e_all, e_active, e_high, e_search)
    if longest < _SLA_SECONDS:
        print(f"OK: 가장 느린 호출도 {longest * 1000:.1f}ms (< {_SLA_SECONDS * 1000:.0f}ms)")
        return 0
    else:
        print(
            f"WARN: 가장 느린 호출이 {longest * 1000:.1f}ms — "
            f"{_SLA_SECONDS * 1000:.0f}ms 초과"
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
