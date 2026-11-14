#!/usr/bin/env bash
# 자동 실행이 바꾼 장부·시세·화면 자료를 저장소에 올린다. 바뀐 것이 없으면 아무 일도 하지 않는다.
# 쓰는 법: bash .github/commit.sh "기록 제목"
set -e
git config user.name "paper-exchange-bot"
git config user.email "paper-exchange-bot@users.noreply.github.com"
git add -A ledger data docs/data
git add -A inbox 2>/dev/null || true
if git diff --cached --quiet; then
  echo "바뀐 것 없음"
  exit 0
fi
git commit -q -m "$1"
for i in 1 2 3 4; do
  if git pull --rebase -q && git push -q; then
    echo "올림: $1"
    exit 0
  fi
  sleep $((i * 5))
done
echo "올리지 못함"
exit 1
