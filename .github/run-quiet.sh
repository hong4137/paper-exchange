#!/usr/bin/env bash
# 공개 저장소의 실행 기록에는 포트폴리오가 찍히면 안 된다(누구나 본다).
# 명령의 출력은 자료 폴더(비공개 저장소)의 logs/ 에만 남기고, 여기에는 끝났는지·실패했는지만 적는다.
# 쓰는 법: bash .github/run-quiet.sh 이름 명령 [인자...]      (PAPER_HOME = 자료 폴더)
set -u
name="$1"; shift
mkdir -p "$PAPER_HOME/logs"
log="$PAPER_HOME/logs/last-$name.log"
echo "# $(TZ=Asia/Seoul date '+%Y-%m-%d %H:%M:%S') $name" > "$log"
if "$@" >> "$log" 2>&1; then
  echo "$name: 끝 (기록은 자료 저장소 logs/last-$name.log)"
else
  code=$?
  fails="$PAPER_HOME/logs/failures.log"
  cat "$log" >> "$fails"
  tail -n 3000 "$fails" > "$fails.tmp" && mv "$fails.tmp" "$fails"
  echo "::error::$name 실패 (종료 코드 $code). 자세한 기록은 자료 저장소 logs/failures.log"
  exit "$code"
fi
