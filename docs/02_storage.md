# 02. 저장소 설계 (파일 기반)

## 2.1 저장 방식 트레이드오프

| 방식 | 장점 | 단점 | 평가 |
|---|---|---|---|
| 단일 JSON에 모든 항목 | 단순, 한번에 로드 | 동시 쓰기 시 전체 락, 파일 비대화, 이미지 별도 처리 복잡 | 수십 건 넘으면 부적합 |
| 항목별 폴더 | 충돌 격리, 항목 단위 백업/삭제, 이미지 결합 | 검색 시 N개 파싱 → 인덱스 필요 | **권장** |
| SQLite | 트랜잭션, 검색 빠름 | 사용자 요구사항 위반 (DB 미사용) | 향후 마이그레이션용으로만 보류 |

→ **항목별 폴더 + 루트 인덱스 파일** 채택.

## 2.2 디렉토리 트리

```
data/
├── index.json                   # 목록/필터 캐시 (가벼운 요약)
├── items/
│   └── 2026-04-28_a3f1b2/       # ID 형식: {YYYY-MM-DD}_{6자 hex}
│       ├── meta.json            # 메타데이터, 상태이력
│       ├── comments.jsonl       # 코멘트 append-only
│       ├── images/
│       │   ├── 001_login_error.png
│       │   ├── 001_login_error.thumb.jpg     # 200px 썸네일
│       │   └── 002_console_capture.png
│       ├── attachments/         # (선택) 추가 파일
│       └── item.log             # 항목별 audit (JSONL)
├── logs/
│   └── audit.log                # 전체 통합 audit (JSONL)
├── backups/
│   └── 2026-04-28T03-00-00/     # 정기 스냅샷
└── .locks/                      # filelock 보관
    ├── index.lock
    └── 2026-04-28_a3f1b2.lock
```

### ID 명명 규칙
- `{YYYY-MM-DD}_{shortid}` — 정렬하면 자연스럽게 시간순
- `shortid`는 `secrets.token_hex(3)` (6자) — 같은 날 1600만 건 정도까진 충돌 거의 없음
- 폴더 이름이 곧 ID, 별도 매핑 테이블 불필요

## 2.3 meta.json 스키마

```json
{
  "schema_version": 1,
  "id": "2026-04-28_a3f1b2",
  "title": "로그인 시 500 에러 발생",
  "description": "OAuth 콜백 후 토큰 교환 단계에서 500 에러. 재현 절차:\n1. ...",
  "urgency": "high",
  "status": "in_progress",
  "author": "김OO",
  "author_role": "reviewer",
  "assignee": "이OO",
  "created_at": "2026-04-28T10:15:32+09:00",
  "updated_at": "2026-04-28T11:02:11+09:00",
  "status_history": [
    {"status": "requested",   "at": "2026-04-28T10:15:32+09:00", "by": "김OO"},
    {"status": "in_progress", "at": "2026-04-28T10:30:00+09:00", "by": "이OO"}
  ],
  "images": [
    {
      "file": "images/001_login_error.png",
      "thumb": "images/001_login_error.thumb.jpg",
      "uploaded_at": "2026-04-28T10:15:32+09:00",
      "sha256": "ab12...ef",
      "size_bytes": 234567
    }
  ],
  "reviewer_confirmed": false,
  "reviewer_confirmed_at": null,
  "tags": ["login", "auth"],
  "archived": false
}
```

### 필드 상세

| 필드 | 타입 | 설명 |
|---|---|---|
| `schema_version` | int | 스키마 변경 시 마이그레이션용 |
| `id` | str | 폴더명과 동일 |
| `title` | str | 1~120자 |
| `description` | str | 마크다운 허용 |
| `urgency` | enum | `"high"` / `"normal"` / `"low"` |
| `status` | enum | `requested`/`in_progress`/`api_check`/`done`/`reviewing`/`reopened`/`closed` (자세한 정의는 [04_workflow.md](04_workflow.md)) |
| `author` | str | 등록자 이름 |
| `author_role` | enum | `"reviewer"` / `"developer"` |
| `assignee` | str \| null | 지정 담당 개발자 (선택) |
| `status_history` | array | 모든 상태 전이 기록 |
| `images` | array | 첨부 이미지 메타 |
| `reviewer_confirmed` | bool | 검토자 최종 OK 여부 |
| `tags` | array | 자유 태그 (검색용) |
| `archived` | bool | true면 기본 목록에서 제외 |

코멘트는 별도 `comments.jsonl`에 저장 (이유는 2.5).

## 2.4 이미지 저장

- 경로: `items/{id}/images/{NNN}_{slug}.{ext}` — 3자리 순번으로 정렬 보장
- `slug`는 한글/공백 안전하게 변환 (`re.sub(r"[^\w\-]", "_", filename_stem)`)
- 업로드 시 즉시 썸네일 생성 (Pillow, 가로 200px) → 목록 카드에서 사용
- sha256 해시를 meta.json에 기록 → 중복 업로드 검출 가능
- 지원 포맷: PNG, JPG, JPEG, GIF, WEBP (≤ 10MB / 파일, 항목당 ≤ 20장)

```python
# core/images.py 의 핵심 로직 (의사 코드)
from PIL import Image, ImageOps

def save_with_thumbnail(upload_file, dest_dir: Path, seq: int) -> dict:
    slug = slugify(Path(upload_file.name).stem)
    ext = Path(upload_file.name).suffix.lower()
    base = dest_dir / f"{seq:03d}_{slug}"

    # 원본
    src = base.with_suffix(ext)
    src.write_bytes(upload_file.getbuffer())

    # 썸네일 (회전 EXIF 보정)
    img = ImageOps.exif_transpose(Image.open(src))
    img.thumbnail((200, 200))
    thumb = base.with_suffix(".thumb.jpg")
    img.convert("RGB").save(thumb, "JPEG", quality=80)

    return {"file": ..., "thumb": ..., "sha256": ..., "size_bytes": src.stat().st_size}
```

## 2.5 코멘트 저장 — JSONL append-only

`comments.jsonl` 한 줄당 한 코멘트:

```jsonl
{"id":"c001","at":"2026-04-28T10:35:00+09:00","author":"이OO","role":"developer","body":"확인했습니다. API 응답 형태가 바뀐 것 같아 외부 팀에 문의 중","kind":"comment"}
{"id":"c002","at":"2026-04-28T11:00:00+09:00","author":"system","role":"system","body":"상태 변경: in_progress → api_check","kind":"system"}
{"id":"c003","at":"2026-04-28T13:20:00+09:00","author":"이OO","role":"developer","body":"답변 받았습니다, 수정 적용 완료","kind":"comment"}
```

**왜 JSONL인가**: 코멘트 추가 시 `meta.json` 전체를 다시 쓰지 않아도 됨. append는 잠금 경합이 적고, 손상 위험도 마지막 한 줄에 한정.

**시스템 코멘트** (`kind: "system"`)로 상태 변경, 첨부 추가, 검토 완료 같은 시스템 이벤트도 같은 타임라인에 기록 → 상세 페이지에서 "무슨 일이 일어났나"를 한 흐름으로 볼 수 있음.

## 2.6 로그 (Audit)

**두 개 다 운영**:

- `data/items/{id}/item.log` (JSONL): 해당 항목의 모든 동작 — 디버깅/감사 용
- `data/logs/audit.log` (JSONL): 전체 통합 — 시스템 활동 한눈에

각 라인 구조:
```json
{"ts":"2026-04-28T10:15:32+09:00","actor":"김OO","action":"create_issue","item_id":"2026-04-28_a3f1b2","detail":{"urgency":"high"}}
```

`action` 종류: `create_issue`, `update_status`, `add_comment`, `upload_image`, `confirm_review`, `archive` 등.

JSONL은 append-only이므로 일반적으로 잠금 불필요하지만, 라인이 길면 `FileLock` 권장.

## 2.7 index.json — 목록 캐시

전체 항목의 요약만 모아 둔 단일 파일. 목록 페이지가 모든 meta.json을 파싱하지 않게 함.

```json
{
  "schema_version": 1,
  "updated_at": "2026-04-28T13:25:00+09:00",
  "items": [
    {
      "id": "2026-04-28_a3f1b2",
      "title": "로그인 시 500 에러",
      "urgency": "high",
      "status": "api_check",
      "author": "김OO",
      "assignee": "이OO",
      "created_at": "2026-04-28T10:15:32+09:00",
      "updated_at": "2026-04-28T13:20:00+09:00",
      "comments_count": 3,
      "images_count": 2,
      "reviewer_confirmed": false,
      "archived": false,
      "tags": ["login", "auth"]
    }
  ]
}
```

### 갱신 규칙
- 항목 생성/수정/삭제/코멘트 추가 시 → 인덱스 잠금 후 해당 항목 엔트리 갱신
- 앱 시작 시 `items/`를 순회하며 인덱스 정합성 검증 (손상/누락 시 재생성)
- 별도 `--rebuild-index` CLI 명령 제공 권장

## 2.8 백업/복구

### 정기 백업 (수동 또는 OS 작업 스케줄러)
1. 글로벌 short-lock 획득 (쓰기 차단, 읽기 허용)
2. `data/items/` + `data/index.json` + `data/logs/` 를 `data/backups/{ISO ts}/`에 복사 (Windows: `robocopy /MIR`)
3. lock 해제

쓰기 도중 단순 폴더 복사를 하면 meta.json은 새 버전인데 image는 옛 버전인 불일치가 발생할 수 있음 → 반드시 lock 후 백업.

### 복구
- 단순: `data/items/`를 백업본으로 교체 후 앱 시작 → 인덱스 자동 재구축
- 부분: 특정 항목 폴더만 복사

### 보존 정책
- 일 1회 백업, 14일분 보관
- 월 1회 별도 외부 저장소(NAS/외장HDD)로 복사 권장

## 2.9 검색/필터 성능

**예상 데이터 규모**: 일 10건 등록, 1년 ≈ 2,500건. index.json 크기 ≈ 1MB 미만 → 메모리 로드 OK.

- 목록 페이지: index.json 한 번만 읽고 pandas DataFrame으로 필터/정렬
- 상세 페이지: 해당 항목의 meta.json + comments.jsonl만 읽음
- 검색: index의 title/tags에 대해 `str.contains()` 기반 부분 매칭으로 충분

만약 1만 건 이상으로 커지면 SQLite 마이그레이션 검토 (이때를 위해 [01_architecture.md](01_architecture.md) 1.6의 인터페이스 추상화).

## 2.10 시간 자동 기록

검토자/개발자가 시간을 직접 입력할 필요는 없음. 모든 시간 필드는 동작 발생 시점에 서버 코드가 자동으로 채운다.

### 동작별 자동 기록 매핑

| 동작 | 자동으로 채워지는 필드 |
|---|---|
| 새 요청 등록 | `meta.json`: `created_at`, `updated_at`, `status_history[0].at` / `audit.log`: `ts` |
| 상태 변경 | `meta.json`: `updated_at`, `status_history[N].at` / `comments.jsonl`: 시스템 이벤트 `at` / `audit.log`: `ts` |
| 코멘트 작성 | `comments.jsonl`: `at` / `meta.json`: `updated_at` / `audit.log`: `ts` |
| 이미지 업로드 | `meta.json`: `images[N].uploaded_at` / `audit.log`: `ts` |
| 검토 완료 | `meta.json`: `reviewer_confirmed_at`, `status_history`에 `closed` 추가 / `audit.log`: `ts` |

### 시간대 정책

- 모든 시간은 **한국 표준시(KST, UTC+9)** 로 저장
- ISO 8601 형식 (오프셋 포함): `2026-04-28T10:15:32+09:00`
- 단일 헬퍼 함수만 사용해서 시간 출처를 한 곳으로 모은다

```python
# core/clock.py
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

def now() -> datetime:
    """공통 현재 시각. 모든 자동 기록은 이 함수만 사용."""
    return datetime.now(KST)
```

`repository.create_issue()`, `add_comment()`, `update_status()` 등은 시간을 인자로 받지 않고 내부에서 `now()`를 호출. 호출자는 시간을 신경 쓸 필요 없음.

### UI 표시 규칙
- 목록 카드 / 타임라인: "2시간 전", "어제 13:20" 같은 상대 시간 (작은 유틸 함수로 변환)
- 마우스 오버 툴팁 또는 상세 페이지에서는 절대 시간 표기 (`2026-04-28 10:15:32`)
- 사용자 입력 폼에는 시간 필드를 노출하지 않음 — 등록 시점이 곧 기록 시점

### 시계 신뢰성

- 공용 PC의 OS 시계가 정확해야 함. Windows 설정 → 날짜 및 시간 → "자동으로 시간 설정" 활성화 확인
- 단일 인스턴스 = 단일 시계라 다중 PC 간 시간 동기화 문제는 발생 안 함
- 만약 시계가 어긋난 채 운영되었더라도 `status_history`와 `audit.log`가 동일 시계로 기록되므로 사후 추적 시 상대 순서는 보존됨
