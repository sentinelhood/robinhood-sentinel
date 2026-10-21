export const addressPattern = /^0x[0-9a-fA-F]{40}$/;
export const hashPattern = /^0x[0-9a-fA-F]{64}$/;
const PUBLIC_RPC = 'https://rpc.mainnet.chain.robinhood.com';
const envRpc = process.env.ROBINHOOD_RPC_URL || '';
const RPC = envRpc.startsWith('https://') ? envRpc : PUBLIC_RPC;
const RPC_LABEL = RPC === PUBLIC_RPC ? 'public-rpc' : 'private-rpc';
async function rpc(method, params = []) {
  const response = await fetch(RPC, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({jsonrpc:'2.0', id:1, method, params}), signal: AbortSignal.timeout(10000)});
  if (!response.ok) throw new Error('RPC unavailable');
  const data = await response.json();
  if (data.error || data.result === undefined) throw new Error('RPC request failed');
  return data.result;
}
const GH = 'https://api.github.com';
async function github(path) {
  const response = await fetch(GH + path, {headers: {Accept: 'application/vnd.github+json', 'User-Agent': 'sentinelhood-site'}, signal: AbortSignal.timeout(10000)});
  if (!response.ok) throw new Error('GitHub unavailable or rate limited');
  return response.json();
}
// Latest review per reviewer decides: any outstanding change request wins over approvals.
export function reviewState(reviews) {
  const latest = new Map();
  for (const r of Array.isArray(reviews) ? reviews : []) {
    if (['APPROVED', 'CHANGES_REQUESTED', 'DISMISSED'].includes(r?.state) && typeof r?.user?.login === 'string') latest.set(r.user.login, r.state);
  }
  const states = [...latest.values()];
  if (states.includes('CHANGES_REQUESTED')) return 'changes_requested';
  if (states.includes('APPROVED')) return 'approved';
  return 'review';
}
export function toContribution(item) {
  const n = item?.number;
  if (!Number.isSafeInteger(n) || n <= 0 || typeof item.title !== 'string' || !item.pull_request) return null;
  const mergedAt = item.pull_request.merged_at;
  const state = mergedAt ? 'merged' : item.state === 'closed' ? 'closed' : 'open';
  const when = (mergedAt || item.closed_at || item.created_at || '').slice(0, 10);
  return {pr: n, title: item.title.slice(0, 160), state, when: /^\d{4}-\d{2}-\d{2}$/.test(when) ? when : ''};
}
async function contributions() {
  const q = encodeURIComponent('repo:aeonfun/aeon is:pr author:sentinelhood');
  const data = await github(`/search/issues?q=${q}&sort=created&order=desc&per_page=20`);
  const prs = (data.items || []).map(toContribution).filter(Boolean);
  await Promise.all(prs.filter((p) => p.state === 'open').map(async (p) => { p.review = reviewState(await github(`/repos/aeonfun/aeon/pulls/${p.pr}/reviews?per_page=100`)); }));
  return {source: 'https://github.com/aeonfun/aeon/pulls?q=author%3Asentinelhood', checkedAt: new Date().toISOString(), prs};
}
export function validate(action, value) {
  if (!['network','address','transaction','aeon','contributions'].includes(action)) throw new Error('Unknown action');
  if (action === 'address' && !addressPattern.test(value || '')) throw new Error('Invalid address');
  if (action === 'transaction' && !hashPattern.test(value || '')) throw new Error('Invalid transaction hash');
  if (action === 'aeon' && (typeof value !== 'string' || value.trim().length < 2 || value.length > 200)) throw new Error('Query must be 2–200 characters');
}
export async function execute(action, value) {
  validate(action, value);
  if (action === 'contributions') return contributions();
  if (action === 'aeon') {
    const response = await fetch(`https://www.aeon.fun/ask?q=${encodeURIComponent(value)}`, {signal: AbortSignal.timeout(10000)});
    if (!response.ok) throw new Error('Aeon unavailable or rate limited');
    const data = await response.json();
    return {source:'https://www.aeon.fun/ask', results: (data.results || []).slice(0,8).filter(r => typeof r.url === 'string' && r.url.startsWith('https://www.aeon.fun/')).map(r => ({name:r.name, description:r.description, url:r.url}))};
  }
  const chainId = Number(BigInt(await rpc('eth_chainId')));
  if (chainId !== 4663) throw new Error('Unexpected RPC chain');
  const block = await rpc('eth_blockNumber');
  const base = {chainId, block: Number(BigInt(block)), checkedAt: new Date().toISOString(), source: RPC_LABEL};
  if (action === 'network') return {...base, gasPriceWei: BigInt(await rpc('eth_gasPrice')).toString()};
  if (action === 'address') {
    const [balance, code, nonce] = await Promise.all([rpc('eth_getBalance',[value,block]), rpc('eth_getCode',[value,block]), rpc('eth_getTransactionCount',[value,block])]);
    return {...base, address:value, balanceWei:BigInt(balance).toString(), codeBytes:(code.length-2)/2, nonce:Number(BigInt(nonce)), warning:'Bytecode presence is not proof of safety. Native balance only; token holdings are not indexed.'};
  }
  const transaction = await rpc('eth_getTransactionByHash',[value]);
  if (!transaction) return {...base, transaction:null, receipt:null};
  const receipt = await rpc('eth_getTransactionReceipt',[value]);
  return {...base, transaction, receipt, warning:'Historical execution only, not a pre-sign simulation or safety verdict.'};
}
// Shared, non-personal reads are edge-cached briefly so many visitors cost one RPC call.
// Address/transaction lookups and every error stay uncached.
export const CACHE = {
  network: 'public, max-age=0, s-maxage=4, stale-while-revalidate=10',
  aeon: 'public, max-age=0, s-maxage=600, stale-while-revalidate=3600',
  // GitHub allows ~60 unauthenticated calls/hour; one refresh costs 1 search + 1 per open PR.
  contributions: 'public, max-age=0, s-maxage=900, stale-while-revalidate=86400',
};

export default async function handler(req, res) {
  res.setHeader('Cache-Control','no-store');
  res.setHeader('X-Content-Type-Options','nosniff');
  res.setHeader('Access-Control-Allow-Origin','*');
  if (req.method !== 'GET') { res.setHeader('Allow','GET'); return res.status(405).json({error:'Only GET is supported'}); }
  const {action, value} = req.query;
  try { validate(action,value); } catch (e) { return res.status(400).json({error:e.message}); }
  try {
    const body = await execute(action,value);
    if (CACHE[action]) res.setHeader('Cache-Control', CACHE[action]);
    return res.status(200).json(body);
  }
  catch { return res.status(502).json({error:'Upstream unavailable, timed out, or chain mismatch. Retry later.'}); }
}