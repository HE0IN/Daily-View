#!/bin/bash
# auto_push.sh — Claude Code 세션 종료 시 자동 commit + push
# 표준 위치: <repo>/.claude/scripts/auto_push.sh
# 트리거: settings.local.json의 SessionEnd / Stop hook
# 정책 (사용자 2026-05-16): "작업할 때마다 Git에 있는 폴더들은 푸시. 상시 최신 유지."

set -e

# 1) 프로젝트 루트로 이동 (CLAUDE_PROJECT_DIR → git toplevel → 스크립트 위치 → pwd 순)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
REPO_DIR="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || echo "$SCRIPT_PROJECT_ROOT")}"
cd "$REPO_DIR" || { echo "[auto_push] cannot cd to $REPO_DIR" >&2; exit 0; }

# 2) git 레포 아니면 skip
if ! git rev-parse --git-dir > /dev/null 2>&1; then
  exit 0
fi

# 3) 변경 없으면 skip
if [ -z "$(git status --porcelain)" ]; then
  exit 0
fi

# 4) 브랜치 확인 (detached HEAD면 skip)
BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null) || exit 0

# 4-a) [Codex 견제 권고 2026-05-16] Secret scan — 흔한 비밀값 패턴 차단
# 변경 파일 중 비밀값 의심되면 push 중단 + 사용자 보고
SUSPECT=$(git diff --cached --no-color 2>/dev/null; git diff --no-color 2>/dev/null) || true
if echo "$SUSPECT" | grep -E -i "(api[_-]?key|secret|token|password|sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN.*PRIVATE KEY-----)" > /dev/null; then
  echo "[auto_push] ⚠ Secret pattern detected — push aborted. 수동 검토 필요." >&2
  echo "[auto_push] 변경 파일: $(git diff --name-only HEAD)" >&2
  exit 0
fi

# 4-b) merge/rebase 중이면 skip (충돌 상태)
if [ -f .git/MERGE_HEAD ] || [ -f .git/REBASE_HEAD ] || [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ]; then
  echo "[auto_push] merge/rebase 진행 중 — push 보류. 정리 후 재시도." >&2
  exit 0
fi

# 5) 자동 commit (현재 모든 변경)
#    자동 스크립트는 '왜' 바꿨는지는 모르므로, '무엇이' 바뀌었는지를 채운다:
#      제목 = 파일 수 + 타임스탬프
#      본문 = 파일별 변경 통계(diff --stat). core.quotepath=false 로 한글 파일명 보존.
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
git add -A
CHANGED_STAT=$(git -c core.quotepath=false diff --cached --stat 2>/dev/null | tail -40)
NFILES=$(git diff --cached --name-only 2>/dev/null | wc -l | tr -d ' ')
git commit -m "[auto] sync ${NFILES} file(s) @ ${TS}" -m "${CHANGED_STAT}" --no-verify 2>&1 | tail -3 || exit 0

# 6) push (실패해도 다음 push로 복구되도록 exit 0 유지)
git push origin "${BRANCH}" 2>&1 | tail -3 || {
  echo "[auto_push] push failed on ${BRANCH} — will retry next session" >&2
  exit 0
}

exit 0
