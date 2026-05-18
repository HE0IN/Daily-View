#!/bin/bash
# auto_pull.sh — Claude Code 세션 시작 시 자동 sync (ff-only 우선, rebase 폴백)
# 표준 위치: <repo>/.claude/scripts/auto_pull.sh
# 트리거: settings.local.json의 SessionStart hook
# 정책: 데스크톱 ↔ 노트북 작업 연속성 자동 보장
# v2 (2026-05-18): "Cannot rebase onto multiple branches" 에러 회피
#   - 단일 ref 명시 fetch
#   - merge --ff-only 우선 (가장 안전), rebase 폴백

set -e

# 프로젝트 루트 (CLAUDE_PROJECT_DIR → git toplevel → 스크립트 위치 → pwd 순)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
REPO_DIR="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || echo "$SCRIPT_PROJECT_ROOT")}"
cd "$REPO_DIR" || exit 0

# git 레포 아니면 skip
if ! git rev-parse --git-dir > /dev/null 2>&1; then exit 0; fi

# 원격 없으면 skip
if ! git remote | grep -q .; then exit 0; fi

# 브랜치 확인 (detached HEAD면 skip)
BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null) || exit 0

# upstream 미설정이면 skip
UPSTREAM=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || echo "")
if [ -z "$UPSTREAM" ]; then exit 0; fi

# upstream에서 remote, remote_branch 추출 (예: origin/main → origin, main)
REMOTE="${UPSTREAM%%/*}"
REMOTE_BRANCH="${UPSTREAM#*/}"

# 로컬 변경 있으면 pull 보류 (충돌 위험)
if [ -n "$(git status --porcelain)" ]; then
  echo "[auto_pull] 로컬 변경 있음. pull 보류. 정리 후 수동 pull 권장." >&2
  exit 0
fi

# 단일 ref만 명시적으로 fetch (multiple branches 에러 회피)
if ! git fetch "$REMOTE" "$REMOTE_BRANCH" 2>/dev/null; then
  echo "[auto_pull] fetch 실패 (네트워크/인증). skip." >&2
  exit 0
fi

# 이미 최신이면 skip
LOCAL_SHA=$(git rev-parse HEAD)
REMOTE_SHA=$(git rev-parse "$UPSTREAM" 2>/dev/null || echo "$LOCAL_SHA")
if [ "$LOCAL_SHA" = "$REMOTE_SHA" ]; then
  exit 0
fi

# 1차: ff-only (가장 안전, 충돌 가능성 0)
if git merge --ff-only "$UPSTREAM" 2>&1 | tail -3; then
  exit 0
fi

# 2차: rebase (단일 ref 명시, multiple branches 에러 회피)
if git rebase "$UPSTREAM" 2>&1 | tail -3; then
  exit 0
fi

# 다 실패 (히스토리 갈라짐) — 보고만, 사용자가 수동 정리
echo "[auto_pull] ff/rebase 둘 다 실패. 히스토리 갈라짐 가능. 'git status' 확인 필요." >&2
exit 0
