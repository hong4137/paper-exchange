// 거래소 화면을 sharktalk 주소에서 내주는 Cloudflare Worker. 모든 요청이 먼저 여기로 온다 (wrangler.toml 의 run_worker_first).
// 하는 일은 lib.mjs 에 있다: 로그인 확인 → 자기 계좌 자료만 → 주문·관리 요청 전달. 화면 파일(docs/*.html)은 통과한 사람에게만 내준다.
import { handle } from './lib.mjs';

export default {
  fetch(request, env) {
    return handle(request, env, () => env.ASSETS.fetch(request));
  },
};
