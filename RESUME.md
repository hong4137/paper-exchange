# RESUME — 거래소 화면 (exchange.sharktalk.co.kr)

집 PC ↔ 회사 PC 에서 이어 하기 위한 기록. 거래소 본체(장부·체결·매시 실행)는 `CLAUDE.md`, 올리는 순서는 `운영-안내.md`.

## 지금 상태 (2026-11-15)
- **올라가 있다.** 워커 `sharktalk-exchange`, 주소 `https://exchange.sharktalk.co.kr`, Cloudflare 개인 계정(paran, sharktalk 가 있는 계정).
- 올리는 명령 (이 폴더에서): `CLOUDFLARE_ACCOUNT_ID=8a7b1e2e89027f9c078fac80ab49d22e npx wrangler deploy`
  올리기 전 `npx wrangler whoami` 로 개인 계정인지 본다. 회사 계정이면 올리지 않는다.
- 로그인하지 않은 요청은 전부 401 로 막힌다 (2026-11-15 직접 요청해 확인: `/`, `/index.html`, `/admin.html`, `/admin`, `/data/league.json`, `/data/state.json`, `/data/accounts/…`, `/data/demo.json`, `/api/me`, `/api/order`, 가짜 쿠키). `workers.dev` 주소는 없다.
- **비밀 설정 두 가지가 아직 없다** → 로그인해도 "거래소 자료를 읽지 못했습니다"가 나온다. 사용자가 직접 넣는다:
  `npx wrangler secret put GITHUB_TOKEN` (저장소 paper-exchange 의 Contents·Issues 읽기/쓰기 토큰, `운영-안내.md` 1번),
  `npx wrangler secret put ADMIN_EMAILS` (관리자의 sharktalk 로그인 이메일, 여럿이면 쉼표).
- 저장소는 아직 공개, GitHub Pages 주소도 아직 열려 있다. 비공개 전환은 확인이 끝난 뒤 사용자가 한다.
- 포털 메뉴에는 올리지 않았다 (따로 정한다).

## 로그인 맞추기에서 확인한 것 (`../sharktalk-auth/index.js`, `../sharktalk-portal/src/index.js` 를 읽고)
- 부르는 방식: service binding `AUTH_SVC` 로 `https://auth.sharktalk.co.kr/me` 에 Cookie 를 넘긴다 — 포털과 같다. 그대로 두었다.
- `/me` 응답: 로그인 안 됨 = 401 `{authenticated: false}`, 로그인 됨 = 200 `{authenticated, user: {email, name, role}}`.
  sharktalk 에는 이메일 말고 따로 "아이디"가 없다 (로그인 화면의 "이용자 ID" 가 이메일이다).
- 쿠키: 이름 `st_session`, `Domain=.sharktalk.co.kr` → `exchange.` 에도 온다. 인증 워커를 바꿀 필요가 없었다.
- 로그인 화면: `https://auth.sharktalk.co.kr/login?next=돌아올주소` (sharktalk 주소만 받는다).
- 관리자 구분: sharktalk-auth 에 `role`(`admin`·`editor`)이 있다. 거래소는 쓰지 않고 `ADMIN_EMAILS` 로 따로 정한다 (지금 결정 그대로).
- 가입: 스스로 가입하는 길이 없다. sharktalk 관리자가 `/admin/create-user` 로 계정을 만들어 준다 (첫 로그인 때 비밀번호 바꾸기 표시).

## 그래서 고친 것 (이 폴더만)
- `site/lib.mjs`
  - `identityFromMe()` 를 실제 모양 하나로 좁혔다: `authenticated === true` 이고 `user.email` 이 이메일일 때만 로그인으로 본다.
  - `st_session` 쿠키가 없으면 인증 워커에 묻지 않고 막는다. `/me` 가 200 이 아니면 막는다.
  - 로그인하러 가기 링크가 `…/login?next=지금 주소` 로 나간다 (로그인하면 거래소로 돌아온다).
  - 통과한 화면에 `cache-control: private, no-store`, `x-robots-tag: noindex, nofollow` (sharktalk 공용 문지기 `shared/gate.js` 와 같게).
- `wrangler.jsonc`: `LOGIN_URL` → `https://auth.sharktalk.co.kr/login`, `compatibility_date` 를 다른 sharktalk 워커와 같은 `2026-09-01` 로.
- `tests/test_site.mjs`: 실제 응답 모양으로 바꾸고, 로그인 없이 막히는 길·쿠키 이름·캐시 머리말 시험을 더했다. `node tests/test_site.mjs` 전부 통과.

## 남은 일
1. (사용자) 비밀 설정 두 가지 넣기.
2. (사용자) 브라우저로 확인 — sharktalk 에 로그인한 뒤 `https://exchange.sharktalk.co.kr`: 본인 계좌가 나오는지, 오른쪽 위 "관리자 화면" 이 보이는지, 관리자 화면에 전체 계좌 표와 "참가자 관리" 양식이 보이는지.
3. 주문 길 확인 — 화면의 주문 양식은 실제 장부에 남는 진짜 주문이다. 아직 한 번도 내 보지 않았다. 사용자가 정한 뒤에 한다.
4. (사용자) 저장소 비공개 전환 (`운영-안내.md` 6번). 그 뒤에 명단에 참가자 이메일을 넣는다 — 공개인 동안에는 넣지 않는다.
5. 포털 메뉴에 올릴지 정하기.

## 알아 둘 것
- 명단(`config.json` players)의 주인 계좌에 이메일이 없어도 된다 — `ADMIN_EMAILS` 에 있는 사람은 주인 계좌의 주인으로 본다.
- 명단의 `login` 칸은 sharktalk 로그인에서는 쓰이지 않는다 (sharktalk 에 아이디가 없다). 참가자는 `email` 로 맞춘다.
- 화면 파일(`docs/*.html`)이나 문지기(`site/`)를 고치면 다시 올려야 반영된다. 자료(`docs/data`)는 올리지 않는다 — 문지기가 저장소에서 읽는다.
- 되돌리기: `npx wrangler delete` (sharktalk 쪽만 내려간다. 거래소 본체와 GitHub Pages 화면은 그대로).
