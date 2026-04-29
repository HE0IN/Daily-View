# 05. 설치 및 실행

## 5.1 사전 준비물

- Windows 10/11 (공용 PC)
- Python 3.12.7 설치
  - [python.org](https://www.python.org/downloads/release/python-3127/) 에서 Windows installer (64-bit) 다운로드
  - 설치 시 "Add python.exe to PATH" 체크
  - 설치 확인:
    ```bash
    py -3.12 --version
    # Python 3.12.7
    ```
- (선택) Git — 코드 버전관리 시

## 5.2 가상환경 + 의존성 설치

프로젝트 루트(`C:\Users\duddl\Desktop\Project\Daily View`)에서:

```bash
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

`requirements.txt` 초안 (구현 시 생성):

```
streamlit>=1.39,<2.0
pydantic>=2.7,<3.0
Pillow>=10.4
filelock>=3.15
python-dotenv>=1.0
pandas>=2.2
streamlit-autorefresh>=1.0
```

## 5.3 환경 설정 (.env)

`.env.example` 복사:

```
# 호스팅
APP_PORT=8501
APP_HOST=0.0.0.0

# 데이터 경로 (절대경로 권장 — 공용 PC라 외장 드라이브 가능)
DATA_DIR=C:\Users\duddl\Desktop\Project\Daily View\data

# 업로드 제한
MAX_UPLOAD_MB=10
MAX_IMAGES_PER_ITEM=20

# 자동 아카이브
AUTO_ARCHIVE_DAYS=14
```

## 5.4 첫 실행

```bash
streamlit run app.py
```

기본 브라우저가 자동으로 `http://localhost:8501`을 염. 사이드바에서 이름과 역할 입력 → 저장.

## 5.5 공용 PC에 띄우기 (사내 네트워크 접속)

### 명령어
```bash
streamlit run app.py ^
  --server.address 0.0.0.0 ^
  --server.port 8501 ^
  --server.headless true ^
  --server.maxUploadSize 50
```

옵션 설명:
- `--server.address 0.0.0.0` — 모든 네트워크 인터페이스에서 수신 (다른 PC에서 접속 가능)
- `--server.port 8501` — 기본 포트, 변경 가능
- `--server.headless true` — 브라우저 자동 실행 안 함
- `--server.maxUploadSize 50` — 업로드 크기 한도(MB), 기본 200MB

### 방화벽 인바운드 허용

PowerShell (관리자 권한):

```powershell
New-NetFirewallRule -DisplayName "Daily View" `
  -Direction Inbound -Action Allow `
  -Protocol TCP -LocalPort 8501 `
  -Profile Private,Domain
```

### 다른 PC에서 접속

공용 PC의 IP 확인:
```bash
ipconfig
```

다른 PC 브라우저에서:
```
http://<공용PC IP>:8501
```

예: `http://192.168.0.50:8501`

## 5.6 시작/종료 스크립트 (편의)

`run.bat`:
```bat
@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
streamlit run app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true
pause
```

더블 클릭으로 실행. 종료는 콘솔 창에서 Ctrl+C.

## 5.7 윈도우 서비스로 등록 (재부팅 후 자동 실행)

[NSSM (Non-Sucking Service Manager)](https://nssm.cc/) 사용:

1. NSSM 다운로드 후 `nssm.exe`를 PATH가 통하는 곳에 둠
2. 관리자 PowerShell에서:
   ```powershell
   nssm install DailyView
   ```
3. GUI에서:
   - **Application path**: `C:\Users\duddl\Desktop\Project\Daily View\.venv\Scripts\streamlit.exe`
   - **Startup directory**: `C:\Users\duddl\Desktop\Project\Daily View`
   - **Arguments**: `run app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true`
   - **I/O 탭**: stdout/stderr 로그 파일 경로 지정
4. 서비스 시작:
   ```powershell
   nssm start DailyView
   ```

상태 확인:
```powershell
Get-Service DailyView
```

## 5.8 백업 스크립트

`backup.bat` (작업 스케줄러로 매일 새벽 3시 실행):

```bat
@echo off
set TS=%date:~0,4%-%date:~5,2%-%date:~8,2%T%time:~0,2%-%time:~3,2%-%time:~6,2%
set TS=%TS: =0%
robocopy "C:\Users\duddl\Desktop\Project\Daily View\data" ^
  "D:\Backups\DailyView\%TS%" /MIR /XD .locks
```

`/XD .locks` — 잠금 파일은 백업 제외.

(앱이 실행 중이라면 5.6에 따라 잠금 처리 권장 — 자세한 내용은 [02_storage.md](02_storage.md) 2.8)

## 5.9 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| 다른 PC에서 접속 안 됨 | 방화벽 인바운드 미허용 / `--server.address 0.0.0.0` 누락 |
| 업로드 시 "File too large" | `--server.maxUploadSize`와 `MAX_UPLOAD_MB` 늘리기 |
| 한글 파일명 깨짐 | 슬러그화 후 저장 (코드에서 처리) |
| `streamlit` 명령어 못 찾음 | venv 활성화 안 됨 → `.venv\Scripts\activate` 다시 |
| 다중 사용자가 동시에 같은 항목 편집 시 충돌 | `core/locking.py`의 `FileLock` 동작 점검, 잠금 파일 잔존 시 `.locks/` 정리 |
| 포트 8501 사용 중 | 다른 포트로 변경 (`--server.port 8502`) 또는 `netstat -ano | findstr 8501` 로 점유 프로세스 확인 |
| 인덱스 손상 후 목록이 안 보임 | `python -m core.index --rebuild` 같은 CLI로 재구축 (구현 필요) |

## 5.10 업그레이드 절차

1. 사용자에게 공지 (5분 다운타임)
2. `nssm stop DailyView`
3. `git pull` (또는 새 버전 파일 덮어쓰기)
4. `pip install -r requirements.txt --upgrade`
5. `nssm start DailyView`
6. 접속 테스트
