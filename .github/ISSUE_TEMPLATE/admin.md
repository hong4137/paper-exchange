---
name: 관리 (거래소 주인만)
about: 참가자를 넣고 빼거나 대회 기간을 정합니다. 주인 계정이 연 이슈만 받습니다 (제목의 [관리] 는 지우지 마세요)
title: "[관리] "
---

```json
{"action": "add_player", "github": "계정 이름", "name": "화면에 나올 이름"}
```

<!--
참가자 빼기     {"action": "remove_player", "github": "계정 이름"}
대회 정하기     {"action": "add_contest", "name": "12월 대회", "start": "2026-12-01", "end": "2026-12-31"}
대회 빼기       {"action": "remove_contest", "name": "12월 대회"}
여러 개는 [ {...}, {...} ] 목록으로 (10개까지).
-->
