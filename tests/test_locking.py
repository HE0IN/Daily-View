"""원자적 쓰기/JSONL append/file_lock 동시성 테스트."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

from core.locking import LOCK_TIMEOUT, atomic_append_jsonl, atomic_write_json, file_lock


# ---------------------------------------------------------------------------
# atomic_write_json
# ---------------------------------------------------------------------------


def test_atomic_write_json_basic(tmp_path: Path) -> None:
    """기본 쓰기 후 파일 존재 + 정상 JSON + 임시파일 없음."""
    target = tmp_path / "out.json"
    payload = {"a": 1, "b": [1, 2, 3], "c": "한글"}
    atomic_write_json(target, payload)

    assert target.exists(), "결과 파일이 만들어지지 않음"
    assert json.loads(target.read_text(encoding="utf-8")) == payload

    # tempfile 흔적이 남지 않아야 한다
    leftover = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftover == [], f"임시 파일 잔존: {leftover}"


def test_atomic_write_json_overwrite(tmp_path: Path) -> None:
    """이미 존재하는 파일 덮어쓰기."""
    target = tmp_path / "out.json"
    target.write_text('{"old": true}', encoding="utf-8")

    new_payload = {"new": [1, 2]}
    atomic_write_json(target, new_payload)

    assert json.loads(target.read_text(encoding="utf-8")) == new_payload


def test_atomic_write_json_creates_parent_dirs(tmp_path: Path) -> None:
    """부모 디렉토리가 없어도 자동 생성."""
    target = tmp_path / "deep" / "nested" / "out.json"
    atomic_write_json(target, {"k": "v"})

    assert target.exists()
    assert json.loads(target.read_text(encoding="utf-8")) == {"k": "v"}


def test_atomic_write_json_concurrent_writes(tmp_path: Path) -> None:
    """5개 스레드가 같은 파일을 동시에 쓰더라도 결과 JSON 은 항상 유효.

    마지막 쓰기 우선이지만 부분 쓰기로 인한 손상이 없어야 한다.
    """
    target = tmp_path / "concurrent.json"

    def writer(i: int) -> None:
        atomic_write_json(target, {"writer": i, "payload": list(range(i, i + 50))})

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(writer, i) for i in range(5)]
        for f in as_completed(futures):
            f.result()  # 예외 전파

    # 결과 파일이 항상 valid JSON 이어야 한다
    raw = target.read_text(encoding="utf-8")
    data = json.loads(raw)  # 손상되었으면 여기서 raise
    assert "writer" in data
    assert 0 <= data["writer"] < 5
    assert isinstance(data["payload"], list)
    assert len(data["payload"]) == 50


# ---------------------------------------------------------------------------
# atomic_append_jsonl
# ---------------------------------------------------------------------------


def test_atomic_append_jsonl_basic(tmp_path: Path) -> None:
    """단일 append 한 줄이 정상 기록."""
    target = tmp_path / "events.jsonl"
    atomic_append_jsonl(target, {"event": "a", "n": 1})
    atomic_append_jsonl(target, {"event": "b", "n": 2})

    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"event": "a", "n": 1}
    assert json.loads(lines[1]) == {"event": "b", "n": 2}


def test_atomic_append_jsonl_concurrent(tmp_path: Path) -> None:
    """10개 스레드 × 5번 append = 50줄 모두 보존, 라인 손상 없음."""
    target = tmp_path / "events.jsonl"
    NUM_THREADS = 10
    APPENDS_PER_THREAD = 5
    EXPECTED = NUM_THREADS * APPENDS_PER_THREAD

    barrier = threading.Barrier(NUM_THREADS)

    def worker(tid: int) -> None:
        # 모든 스레드가 동시에 시작하도록 barrier 사용 → 경합 강제
        barrier.wait()
        for n in range(APPENDS_PER_THREAD):
            atomic_append_jsonl(target, {"tid": tid, "n": n})

    with ThreadPoolExecutor(max_workers=NUM_THREADS) as pool:
        futures = [pool.submit(worker, t) for t in range(NUM_THREADS)]
        for f in as_completed(futures):
            f.result()

    raw_text = target.read_text(encoding="utf-8")
    lines = [ln for ln in raw_text.splitlines() if ln.strip()]
    assert len(lines) == EXPECTED, (
        f"라인 손실: {len(lines)} / {EXPECTED} 줄. 일부 append 가 누락됨."
    )

    # 각 줄이 독립된 JSON object 로 파싱되어야 한다 (라인 섞임 없음)
    seen: set[tuple[int, int]] = set()
    for ln in lines:
        obj = json.loads(ln)
        assert "tid" in obj and "n" in obj, f"라인 구조 깨짐: {ln!r}"
        seen.add((obj["tid"], obj["n"]))

    expected_pairs = {
        (t, n) for t in range(NUM_THREADS) for n in range(APPENDS_PER_THREAD)
    }
    assert seen == expected_pairs, (
        f"기대값 {len(expected_pairs)}개 vs 관측 {len(seen)}개 — 누락/중복 발생"
    )


def test_atomic_append_jsonl_korean_payload(tmp_path: Path) -> None:
    """한글 payload 가 UTF-8 로 정상 보존."""
    target = tmp_path / "ko.jsonl"
    atomic_append_jsonl(target, {"body": "안녕하세요", "kind": "한글"})

    line = target.read_text(encoding="utf-8").strip()
    obj = json.loads(line)
    assert obj == {"body": "안녕하세요", "kind": "한글"}


# ---------------------------------------------------------------------------
# file_lock
# ---------------------------------------------------------------------------


def test_file_lock_context_manager(tmp_path: Path) -> None:
    """file_lock 의 with 진입/종료가 정상 동작."""
    lock_path = tmp_path / "subdir" / "my.lock"
    # 부모 디렉토리는 file_lock 이 생성해야 함
    assert not lock_path.parent.exists()

    lock = file_lock(lock_path)
    assert lock_path.parent.exists(), "file_lock 가 부모 디렉토리를 만들지 않음"

    with lock:
        # 락 보유 중에는 is_locked 가 True
        assert lock.is_locked, "with 진입 후 락이 잡히지 않음"

    assert not lock.is_locked, "with 종료 후에도 락이 풀리지 않음"


def test_file_lock_timeout_param(tmp_path: Path) -> None:
    """timeout 파라미터가 FileLock 인스턴스에 전달됨."""
    lock_path = tmp_path / "to.lock"
    lock = file_lock(lock_path, timeout=2.5)
    assert lock.timeout == 2.5, f"timeout 미반영: {lock.timeout}"

    # 기본값
    default_lock = file_lock(tmp_path / "to2.lock")
    assert default_lock.timeout == LOCK_TIMEOUT
