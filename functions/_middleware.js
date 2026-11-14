// Cloudflare Pages 가 모든 요청 앞에서 부르는 문지기. 하는 일은 site/lib.mjs 에 있다.
import { handle } from '../site/lib.mjs';

export const onRequest = (context) => handle(context.request, context.env, () => context.next());
