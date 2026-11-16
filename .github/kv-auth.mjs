// 로그인 창고(Cloudflare KV) — site-deploy 가 쓴다. 공개 실행 기록에 내용을 찍지 않는다(개수·끝만).
//   node .github/kv-auth.mjs ensure   → 창고가 없으면 만들고, 그 번호를 wrangler.jsonc 에 묶음 AUTH 로 넣는다 (저장소에는 올리지 않는다 — 이 실행 안에서만)
//   node .github/kv-auth.mjs migrate  → 자료 저장소 players.json 에 남은 비밀번호·열쇠 지문을 창고로 옮기고, 옮긴 것이 있으면 명단에서 지우라는 관리 요청(purge_secrets)을 올린다
// 필요한 것: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID, (migrate) DATA_TOKEN
import fs from 'node:fs';

const TITLE = 'sharktalk-exchange-auth';
const ACCT = process.env.CLOUDFLARE_ACCOUNT_ID;
const CF = `https://api.cloudflare.com/client/v4/accounts/${ACCT}/storage/kv/namespaces`;
const cf = (path, init = {}) => fetch(CF + path, { ...init, headers: { Authorization: `Bearer ${process.env.CLOUDFLARE_API_TOKEN}`, ...(init.headers || {}) } });
const DATA = 'https://api.github.com/repos/hong4137/paper-exchange-data/contents';
const gh = (path, init = {}) => fetch(`${DATA}/${path}`, { ...init, headers: { Authorization: `Bearer ${process.env.DATA_TOKEN}`, Accept: 'application/vnd.github+json', 'User-Agent': 'site-deploy', ...(init.headers || {}) } });
const die = (msg) => { console.log(`::error::${msg}`); process.exit(1); };

async function namespaceId() {
  for (let page = 1; page < 20; page++) {
    const r = await cf(`?per_page=100&page=${page}`);
    if (!r.ok) die(`로그인 창고 목록을 읽지 못했습니다 (${r.status}) — Cloudflare 열쇠에 "Workers KV Storage: Edit" 권한이 있는지 보세요`);
    const j = await r.json();
    const hit = (j.result || []).find((n) => n.title === TITLE);
    if (hit) return hit.id;
    if (!j.result || j.result.length < 100) break;
  }
  return null;
}

const mode = process.argv[2];
let id = await namespaceId();
if (!id) {
  if (mode !== 'ensure') die('로그인 창고가 없습니다');
  const r = await cf('', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ title: TITLE }) });
  if (!r.ok) die(`로그인 창고를 만들지 못했습니다 (${r.status}) — Cloudflare 열쇠에 "Workers KV Storage: Edit" 권한이 있는지 보세요`);
  id = (await r.json()).result.id;
  console.log('로그인 창고를 새로 만들었습니다');
}

if (mode === 'ensure') {
  const p = 'wrangler.jsonc';
  const s = fs.readFileSync(p, 'utf8');
  if (!s.includes('"kv_namespaces"')) {
    const anchor = '  "assets":';
    if (!s.includes(anchor)) die('wrangler.jsonc 에서 넣을 자리를 찾지 못했습니다');
    fs.writeFileSync(p, s.replace(anchor, `  "kv_namespaces": [{ "binding": "AUTH", "id": "${id}" }],\n${anchor}`));
  }
  console.log('로그인 창고를 문지기에 묶었습니다');
} else if (mode === 'migrate') {
  if (!process.env.DATA_TOKEN) { console.log('DATA_TOKEN 이 없어 옮기지 않았습니다'); process.exit(0); }
  const r = await gh('players.json?ref=main');
  if (!r.ok) die(`명단을 읽지 못했습니다 (${r.status})`);
  const players = JSON.parse(Buffer.from((await r.json()).content, 'base64').toString('utf8')).players || [];
  const get = async (k) => { const x = await cf(`/${id}/values/${encodeURIComponent(k)}`); return x.ok ? x.text() : null; };
  const put = async (k, v) => { const x = await cf(`/${id}/values/${encodeURIComponent(k)}`, { method: 'PUT', body: JSON.stringify(v) }); if (!x.ok) die(`창고에 쓰지 못했습니다 (${x.status})`); };
  let moved = 0, left = 0;
  for (const p of players) {
    const pid = String(p.id || p.github || '').toLowerCase();
    if (!pid) continue;
    if (p.api_keys || p.password) left++;
    if ((p.api_keys || []).length && !(await get(`keys:${pid}`))) {   // 창고에 이미 열쇠가 있으면 그쪽이 새것 — 명단 것은 옮기지 않는다
      const hashes = p.api_keys.map((k) => String(k.hash)).filter((h) => /^[0-9a-f]{64}$/.test(h));
      for (const k of p.api_keys) if (/^[0-9a-f]{64}$/.test(String(k.hash))) await put(`key:${k.hash}`, { id: pid, created: k.created || null, label: k.label || '' });
      await put(`keys:${pid}`, hashes);
      moved++;
    }
    if (p.password && !(await get(`pw:${pid}`))) { await put(`pw:${pid}`, { hash: p.password, at: p.password_at || null }); moved++; }
  }
  console.log(`옮긴 계좌 ${moved}곳, 명단에 지문이 남아 있던 계좌 ${left}곳`);
  if (left) {
    const stamp = new Date().toISOString().replace(/[-:.TZ]/g, '').slice(0, 17);
    const body = { action: 'purge_secrets', requested_at: new Date().toISOString() };
    const w = await gh(`admin/${stamp}-purge.json`, { method: 'PUT', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ message: '관리 요청 purge_secrets', branch: 'main', content: Buffer.from(JSON.stringify(body)).toString('base64') }) });
    if (!w.ok) die(`명단에서 지우라는 요청을 올리지 못했습니다 (${w.status})`);
    console.log('명단에서 지문을 지우라는 관리 요청을 올렸습니다');
  }
}
