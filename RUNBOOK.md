# Daily View 운영 매뉴얼 (RUNBOOK)

> 운영자/배포 담당자용 단일 실행 가이드.
> 설계 배경은 [`docs/`](docs/) 폴더, 본 문서는 **명령어 위주**.

---

## 1. 첫 설치

### 사전 요구

- Windows 10/11 (관리자 권한 가능한 계정)
- Python **3.12.7**
  - 설치 시 "Add python.exe to PATH" 체크
  - 확인: `py -3.12 --version`
- (선택) Git — 코드 갱신 시 사용

### 가상환경 + 패키지

프로젝트 루트(`C:\Users\duddl\Desktop\Project\Daily View`)에서:

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

설치되는 주요 패키지:

| 패키지 | 용도 |
|---|---|
| `streamlit` | 웹 UI 프레임워크 |
| `pydantic` | 도메인 모델 검증 |
| `Pillow` | 이미지 처리/썸네일 |
| `filelock` | 동시성 제어 |
| `python-dotenv` | `.env` 로드 |
| `pandas` | 통계 페이지 |
| `streamlit-autorefresh` | 30초 자동 새로고침 |
| `streamlit-paste-button` | 클립보드 붙여넣기 |
| `tzdata` | Windows ZoneInfo 지원 |

### 환경변수 (.env)

`.env.example` 을 복사:

```bat
copy .env.example .env
```

기본값 그대로 두어도 동작. 변경할 수 있는 항목:

```ini
APP_PORT=8501
APP_HOST=0.0.0.0
DATA_DIR=C:\Users\duddl\Desktop\Project\Daily View\data
MAX_UPLOAD_MB=10
MAX_IMAGES_PER_ITEM=20
AUTO_ARCHIVE_DAYS=14
AUTO_REFRESH_SEC=30        # 0 으로 설정 시 자동 새로고침 비활성
```

### 첫 실행 (로컬 테스트)

```bat
.venv\Scripts\activate
streamlit run app.py
```

브라우저가 자동으로 `http://localhost:8501` 을 연다. 사이드바에서 이름과
역할(검토자/개발자) 입력 → [저장]. 메인 화면이 뜨면 정상.

---

## 2. 공용 PC 호스팅

### 2-1. Streamlit 띄우기

`scripts\run.bat` 더블클릭 또는:

```bat
streamlit run app.py ^
  --server.address 0.0.0.0 ^
  --server.port 8501 ^
  --server.headless true ^
  --server.maxUploadSize 50
```

### 2-2. 방화벽 인바운드 허용

PowerShell **관리자 권한**:

```powershell
New-NetFirewallRule -DisplayName "Daily View" `
  -Direction Inbound -Action Allow `
  -Protocol TCP -LocalPort 8501 `
  -Profile Private,Domain
```

### 2-3. 공용 PC IP 확인 / 다른 PC 접속

```bat
ipconfig
```

`IPv4 주소` 메모. 다른 PC 브라우저에서:

```
http://<공용PC IP>:8501
```

예: `http://192.168.0.50:8501`

---

## 3. NSSM 서비스 등록 (재부팅 후 자동 시작)

[NSSM](https://nssm.cc/) 다운로드 후 `nssm.exe` 를 PATH 에 추가.

```powershell
# 관리자 PowerShell
nssm install DailyView
```

GUI 가 뜨면:

| 탭 | 항목 | 값 |
|---|---|---|
| Application | Path | `C:\Users\duddl\Desktop\Project\Daily View\.venv\Scripts\streamlit.exe` |
| Application | Startup directory | `C:\Users\duddl\Desktop\Project\Daily View` |
| Application | Arguments | `run app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true --server.maxUploadSize 50` |
| I/O | Output (stdout) | `C:\Users\duddl\Desktop\Project\Daily View\data\logs\nssm-stdout.log` |
| I/O | Error (stderr) | `C:\Users\duddl\Desktop\Project\Daily View\data\logs\nssm-stderr.log` |
| Details | Startup type | Automatic |

`Install service` 클릭 후:

```powershell
nssm start DailyView
Get-Service DailyView          # Status: Running 확인
```

서비스 중지/제거:

```powershell
nssm stop DailyView
nssm remove DailyView confirm
```

---

## 4. 일일 백업 스케줄링

### 4-1. 백업 스크립트

`scripts\backup.bat` 사용. 기본 백업 위치: `D:\Backups\DailyView\<TIMESTAMP>`.
변경하려면 환경변수 `BACKUP_ROOT` 설정.

수동 실행 (테스트):

```bat
scripts\backup.bat
```

성공 시 종료코드 0. 14일 이상 된 백업 폴더는 자동 삭제.

### 4-2. 작업 스케줄러 등록

PowerShell **관리자 권한**:

```powershell
$action = New-ScheduledTaskAction `
  -Execute "C:\Users\duddl\Desktop\Project\Daily View\scripts\backup.bat"
$trigger = New-ScheduledTaskTrigger -Daily -At 3:00AM
$principal = New-ScheduledTaskPrincipal `
  -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName "DailyView Backup" `
  -Action $action -Trigger $trigger -Principal $principal `
  -Description "Daily View data daily backup at 03:00"
```

확인:

```powershell
Get-ScheduledTask -TaskName "DailyView Backup"
```

수동 실행 (스케줄러 통해):

```powershell
Start-ScheduledTask -TaskName "DailyView Backup"
```

---

## 5. 업그레이드 절차

```powershell
# 1) 사용자에게 5분 다운타임 공지 (Slack/Teams 등)
nssm stop DailyView

# 2) 코드 갱신
cd "C:\Users\duddl\Desktop\Project\Daily View"
git pull        # Git 사용 시
# 또는: 새 버전 파일을 덮어쓰기

# 3) 의존성 갱신
.venv\Scripts\activate
pip install -r requirements.txt --upgrade

# 4) 테스트 (선택, 강력 권장)
python -m pytest tests/ -q

# 5) 시작 + 접속 테스트
nssm start DailyView
Start-Sleep -Seconds 5
curl http://localhost:8501           # 응답 확인
```

---

## 6. 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| 포트 8501 사용 중 | `netstat -ano | findstr 8501` → 점유 PID 확인 → `taskkill /PID <PID> /F` 또는 다른 포트 (`--server.port 8502`) |
| 다른 PC 에서 접속 안 됨 | (1) 방화벽 인바운드 미허용 (`Get-NetFirewallRule -DisplayName "Daily View"`) (2) `--server.address 0.0.0.0` 누락 (3) 같은 네트워크인지 확인 |
| 인덱스 손상 후 목록이 비어 보임 | `python scripts\rebuild_index.py` — 자동 점검도 앱 시작 시 1회 실행되지만, 강제 재구축이 필요할 때 직접 호출 |
| 한글 파일명/제목 깨짐 | (1) 모든 I/O 가 UTF-8 (코드에서 보장) (2) `.bat` 파일 자체는 cp949/UTF-8 (no BOM) 어느 쪽이든 동작. UTF-8 BOM 은 `.bat` 에서 깨질 수 있으니 사용 금지 |
| 업로드 시 "File too large" | `.env` 의 `MAX_UPLOAD_MB` 와 `--server.maxUploadSize` 둘 다 늘리기 |
| 동시 편집 충돌 / 잠금 잔존 | `data\.locks\` 폴더의 `.lock` 파일들을 모두 삭제 후 재시작 (정상 종료 후 자동 정리되지만 강제 종료 시 잔존 가능) |
| Streamlit 명령어 못 찾음 | venv 활성화가 안 됨 → `.venv\Scripts\activate` 다시 실행 |
| NSSM 서비스가 시작 후 바로 Stopped | I/O 로그 (`data\logs\nssm-stderr.log`) 확인. 보통 `.env` 누락 또는 `streamlit.exe` 경로 오류 |
| 자동 새로고침이 안 됨 | (1) `streamlit-autorefresh` 가 설치되었는지 (`pip show streamlit-autorefresh`) (2) `.env` 의 `AUTO_REFRESH_SEC` 가 0 이 아닌지 |

---

## 7. M3 검증 체크리스트

`docs/06_implementation_plan.md` 6.4 절 항목을 실제 운영 환경에서 확인.

### 자동 검증 가능 (CI/스크립트)

| # | 항목 | 명령어 | 기대 |
|---|---|---|---|
| 1 | pytest 75건 통과 | `python -m pytest tests/ -v` | `75 passed` |
| 2 | 한글 제목/파일명 처리 | `python scripts\seed_dummy.py --count 50` | 한글 항목 50건 생성 성공 |
| 3 | 1년치 부하 (2,500건) 응답시간 | `python scripts\seed_dummy.py --count 2500` 후 `python scripts\perf_check.py` | 모든 호출 < 1000ms |
| 4 | 동시성 (filelock) | `python -m pytest tests/test_locking.py -v` | 9 passed (loss-free 동시 append 검증) |
| 5 | 인덱스 손상 복구 | `del data\index.json` → `python scripts\rebuild_index.py` | rebuild 후 verify 통과 |
| 6 | 강제 종료 후 자동 인덱스 검증 | 앱 강제 종료 → 재시작 시 부트스트랩이 verify_index 후 필요 시 자동 rebuild + toast |

### 수동 검증 필요

| # | 항목 | 검증 방법 |
|---|---|---|
| 1 | 두 사용자 동시 등록 | 다른 PC 또는 시크릿 창 2개로 동시에 [새 요청 등록] → 둘 다 저장됨 확인 |
| 2 | 두 사용자 동시 코멘트 | 같은 항목을 두 창에서 열고 거의 동시에 [등록] → 둘 다 보존 |
| 3 | 동시 상태 변경 | 두 창에서 같은 항목 상태 변경 → 마지막 쓰기 우선, 실패 시 워크플로우 가드가 막음 |
| 4 | 다른 PC 복원 | `data\` 폴더만 다른 PC 로 복사 → 같은 절차로 실행 시 모든 항목/이미지 정상 표시 |
| 5 | 사내 다중 PC 접속 | 검토자 1명 + 개발자 1명이 각자 PC 에서 1주 사용, 누적 데이터 손실/충돌 없음 |
| 6 | Windows 재부팅 후 NSSM 자동 시작 | PC 재부팅 → 1분 후 `Get-Service DailyView` 가 Running |
| 7 | 10MB 이미지 업로드 | 1장 첨부 → 정상 표시, 썸네일 자동 생성 |

---

## 8. 폴더 구조 (운영자 시야)

```
C:\Users\duddl\Desktop\Project\Daily View\
├── app.py                    # 진입점 (대시보드)
├── pages\                    # 요청목록/등록/상세/통계
├── core\                     # 도메인 + 저장소 (수정 X)
├── ui\                       # 공용 UI (수정 X)
├── tests\                    # pytest 75건
├── scripts\
│   ├── run.bat               # 시작 스크립트
│   ├── backup.bat            # 일일 백업
│   ├── seed_dummy.py         # 더미 데이터 생성 (성능/한글 검증)
│   ├── rebuild_index.py      # 인덱스 재구축 CLI
│   └── perf_check.py         # list_issues 응답시간 측정
├── data\                     # 런타임 데이터 (백업 대상)
│   ├── items\<id>\           # meta.json + comments.jsonl + images\
│   ├── index.json            # 목록 캐시 (자동 재구축 가능)
│   ├── logs\audit.log        # 전체 audit 로그
│   ├── backups\              # (사용 안 함; 외부 디스크에 백업 권장)
│   └── .locks\               # filelock 작업 파일
├── .env                      # 운영 환경변수 (커밋 X)
├── .env.example              # 템플릿
├── requirements.txt
├── RUNBOOK.md                # ← 본 문서
├── README.md
└── docs\                     # 설계 문서 (01~07)
```

---

## 9. 빠른 명령 카드

```bat
REM 일상 운영
nssm start DailyView                      :: 서비스 시작
nssm stop DailyView                       :: 서비스 종료
Get-Service DailyView                     :: 상태 확인
type data\logs\audit.log | more           :: 최근 활동 로그

REM 점검 / 복구
python -m pytest tests/ -q                :: 테스트
python scripts\rebuild_index.py           :: 인덱스 재구축
python scripts\perf_check.py              :: 성능 측정

REM 백업
scripts\backup.bat                        :: 수동 백업
```

문제 발생 시 점검 순서:

1. `Get-Service DailyView` — 서비스 살아 있는가
2. `data\logs\nssm-stderr.log` — 시작 단계 에러
3. `data\logs\audit.log` — 마지막 정상 동작 시점
4. `python scripts\rebuild_index.py` — 인덱스 정합성 회복
5. 그래도 안 되면 → 최신 백업으로 `data\` 통째로 복원
