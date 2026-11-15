#!/usr/bin/env bash
# 자동 실행이 바꾼 자료(장부·시세·화면 자료·기록)를 비공개 자료 저장소에 올린다. 바뀐 것이 없으면 아무 일도 하지 않는다.
# 파일 이름도 공개 실행 기록에 남기지 않는다 (git 출력은 모두 버린다).
# 쓰는 법: bash .github/commit-data.sh "기록 제목"      (PAPER_HOME = 자료 저장소를 받아 둔 폴더)
set -u
cd "$PAPER_HOME"
git config user.name "paper-exchange-bot"
git config user.email "paper-exchange-bot@users.noreply.github.com"
git add -A . >/dev/null 2>&1
if git diff --cached --quiet; then
  echo "바뀐 것 없음"
  exit 0
fi
git commit -q -m "$1" >/dev/null 2>&1
for i in 1 2 3 4; do
  if git pull --rebase -q origin main >/dev/null 2>&1 && git push -q origin HEAD:main >/dev/null 2>&1; then
    echo "자료 저장소에 올림: $1"
    exit 0
  fi
  git rebase --abort >/dev/null 2>&1
  sleep $((i * 5))
done
echo "::error::자료 저장소에 올리지 못했습니다"
exit 1
