"""파일 잠금 및 원자적 쓰기 헬퍼.

docs/01_architecture.md 1.5 절의 패턴을 그대로 구현한다.

- 락 파일은 대상 경로에 ``.lock`` 접두 확장자를 덧붙여 사용:
  ``foo/bar.json`` → ``foo/bar.json.lock``
- 단일 JSON 갱신: tempfile + ``os.replace`` + ``fsync`` 로 원자성 보장.
- JSONL append: PIPE_BUF 한계를 초과할 가능성에 대비해 항상 락을 걸고 한 줄 append.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from filelock import FileLock

LOCK_TIMEOUT: float = 5.0


def file_lock(lock_path: Path, *, timeout: float = LOCK_TIMEOUT) -> FileLock:
    """FileLock 인스턴스를 생성해 반환 (with 문에서 사용).

    호출자가 직접 잠금 단위를 제어해야 할 때 사용. 단일 파일 갱신은
    :func:`atomic_write_json` / :func:`atomic_append_jsonl` 가 내부적으로
    처리하므로 보통 직접 호출할 필요는 없다.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    return FileLock(str(lock_path), timeout=timeout)


def _write_json_unlocked(path: Path, data: dict | list) -> None:
    """tempfile + os.replace 로 JSON 을 원자적으로 기록 (락 없음).

    이미 외부에서 동일 경로의 락을 잡고 있는 경우 이 함수를 직접 사용한다.
    Windows FileLock 은 같은 경로에 대해 두 개의 인스턴스로 재진입 락을 지원하지
    않기 때문에, 락 보유 중인 코드 경로는 :func:`atomic_write_json` 대신 본 함수를
    호출해야 한다.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
        suffix=".tmp",
    )
    try:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, path)  # POSIX/Windows 모두 원자적
    except Exception:
        tmp.close()
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


def atomic_write_json(
    path: Path,
    data: dict | list,
    *,
    timeout: float = LOCK_TIMEOUT,
) -> None:
    """JSON 직렬화 가능한 데이터를 원자적으로 파일에 기록.

    부모 디렉토리는 없으면 생성한다. 락 파일은 ``path`` 에 ``.lock`` 접두 확장자를
    붙인 위치에 만든다. 임시 파일 → ``os.replace`` 로 교체하므로 부분 쓰기로
    파일이 손상될 가능성이 없다.

    호출자가 이미 동일 경로 락을 보유 중이라면 :func:`_write_json_unlocked` 를 사용.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")

    with FileLock(str(lock_path), timeout=timeout):
        _write_json_unlocked(path, data)


def atomic_append_jsonl(
    path: Path,
    line_obj: dict,
    *,
    timeout: float = LOCK_TIMEOUT,
) -> None:
    """단일 dict를 JSON 직렬화하여 한 줄 append.

    PIPE_BUF(보통 4096바이트) 를 초과하면 OS의 append 원자성이 깨질 수 있어
    항상 파일 락으로 직렬화한다. 부모 디렉토리는 없으면 생성한다.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    line = json.dumps(line_obj, ensure_ascii=False) + "\n"

    with FileLock(str(lock_path), timeout=timeout):
        with open(path, mode="a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())


__all__ = [
    "LOCK_TIMEOUT",
    "file_lock",
    "atomic_write_json",
    "atomic_append_jsonl",
    "_write_json_unlocked",
]
