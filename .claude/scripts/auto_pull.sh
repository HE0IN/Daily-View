#!/bin/bash
# auto_pull.sh — Claude Code 세션 시작 시 자동 git pull --rebase
# 표준 위치: <repo>/.claude/scripts/auto_pull.sh
# 트리거: settings.local.json의 SessionStart hook
# 정책 (사용자 2026-05-16): 데스크톱 ↔ 노트북 작업 연속성 자동 보장

set -e

REPO_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
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

# 로컬 변경 있으면 pull 보류 (충돌 위험)
if [ -n "$(git status --porcelain)" ]; then
  echo "[auto_pull] 로컬 변경 있음. pull 보류. 정리 후 수동 pull 권장." >&2
  exit 0
fi

# rebase로 pull (--ff-only도 안전 옵션이지만, rebase가 더 매끄러움)
if git pull --rebase 2>&1 | tail -3; then
  exit 0
else
  echo "[auto_pull] pull --rebase 실패. 수동 확인 필요." >&2
  exit 0
fi
