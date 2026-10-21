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
// ---------- token check (ERC-20 metadata + Pons v2 factory record) ----------
export const PONS_FACTORY = '0x7eD598BcEf8bd9Edd8C97A195C6d13f40801EC7e';
const SEL = {launch: '0x3cf28b5a', feeBps: '0x24a9d853', name: '0x06fdde03', symbol: '0x95d89b41', decimals: '0x313ce567', supply: '0x18160ddd', balanceOf: '0x70a08231'};
const ZERO_ADDR = '0x' + '0'.repeat(40);
// EIP-7702: an EOA that delegates to a contract carries exactly 0xef0100 || address. It is a wallet, not a contract.
export function delegation(code) {
  const m = /^0xef0100([0-9a-fA-F]{40})$/.exec(code || '');
  return m ? '0x' + m[1].toLowerCase() : null;
}
const pad = (a) => a.toLowerCase().replace(/^0x/, '').padStart(64, '0');
const words = (hex) => (typeof hex === 'string' && /^0x([0-9a-fA-F]{64})*$/.test(hex) ? hex.slice(2).match(/.{64}/g) || [] : []);
const wAddr = (w) => '0x' + w.slice(24);
const wUint = (w) => BigInt('0x' + w);
const wInt = (w) => { const v = wUint(w); return v >= 2n ** 255n ? v - 2n ** 256n : v; };
// getLaunchedToken returns a 15-word static struct; an unknown token returns all zeros (exists = false).
export function decodeLaunch(hex) {
  const w = words(hex);
  if (w.length !== 15) throw new Error('Unexpected factory response');
  if (wUint(w[14]) !== 1n) return null;
  return {
    token: wAddr(w[0]), curve: wAddr(w[1]), deployer: wAddr(w[2]), creatorFeeRecipient: wAddr(w[3]), pairToken: wAddr(w[4]),
    graduationThresholdWei: wUint(w[5]).toString(), poolFee: Number(wUint(w[6])), tickSpacing: Number(wInt(w[7])),
    creatorTaxBps: Number(wUint(w[8])), buybackEnabled: wUint(w[9]) === 1n, phase: Number(wUint(w[10])),
  };
}
// ABI string, with a bytes32 fallback for old tokens. Control characters stripped, length capped.
export function decodeString(hex) {
  const w = words(hex);
  let bytes = '';
  if (w.length >= 2 && wUint(w[0]) === 32n && wUint(w[1]) <= BigInt((w.length - 2) * 32)) bytes = w.slice(2).join('').slice(0, Number(wUint(w[1])) * 2);
  else if (w.length === 1) bytes = w[0].replace(/(00)+$/, '');
  else return null;
  return Buffer.from(bytes, 'hex').toString('utf8').replace(/[\u0000-\u001f\u007f-\u009f\ufffd]/g, '').trim().slice(0, 64) || null;
}
export function formatUnits(raw, decimals, places = 4) {
  const base = 10n ** BigInt(decimals);
  const whole = (raw / base).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  const frac = (raw % base).toString().padStart(decimals, '0').slice(0, places).replace(/0+$/, '');
  return whole + (frac ? '.' + frac : '');
}
export function percentOf(part, total) {
  if (total <= 0n) return null;
  const scaled = part * 1000000n / total;
  return `${scaled / 10000n}.${(scaled % 10000n).toString().padStart(4, '0')}`;
}
async function call(to, data, block) {
  try { return await rpc('eth_call', [{to, data}, block]); } catch { return null; }
}
async function tokenCheck(address, block) {
  const [nameHex, symbolHex, decHex, supplyHex, launchHex] = await Promise.all([
    call(address, SEL.name, block), call(address, SEL.symbol, block), call(address, SEL.decimals, block),
    call(address, SEL.supply, block), call(PONS_FACTORY, SEL.launch + pad(address), block)]);
  const decimals = words(decHex).length === 1 ? Number(wUint(words(decHex)[0])) : null;
  const supply = words(supplyHex).length === 1 ? wUint(words(supplyHex)[0]) : null;
  const erc20 = decimals !== null && decimals <= 36 && supply !== null;
  if (launchHex === null) throw new Error('Factory read failed');
  const launch = decodeLaunch(launchHex);
  if (launch && launch.token.toLowerCase() !== address.toLowerCase()) throw new Error('Factory record mismatch');
  if (launch) {
    const w = words(await call(launch.curve, SEL.feeBps, block));
    launch.baseFeeBps = w.length === 1 && wUint(w[0]) <= 10000n ? Number(wUint(w[0])) : null;
  }
  let holders = [];
  if (launch && erc20) {
    const roles = new Map();
    for (const [r, a] of [['Deployer', launch.deployer], ['Fee recipient', launch.creatorFeeRecipient]]) {
      if (a !== ZERO_ADDR) roles.set(a, roles.has(a) ? `${roles.get(a)} + fee recipient` : r);
    }
    const who = [...roles.entries()];
    holders = await Promise.all(who.map(async ([a, role]) => {
      const w = words(await call(address, SEL.balanceOf + pad(a), block));
      if (w.length !== 1) return {role, address: a, balance: null, percent: null};
      const bal = wUint(w[0]);
      return {role, address: a, balance: formatUnits(bal, decimals), percent: percentOf(bal, supply)};
    }));
  }
  return {
    erc20, name: erc20 ? decodeString(nameHex) : null, symbol: erc20 ? decodeString(symbolHex) : null,
    decimals: erc20 ? decimals : null, totalSupply: erc20 ? formatUnits(supply, decimals) : null,
    pons: launch && {...launch, factory: PONS_FACTORY, holders},
    warning: 'Read-only on-chain facts. A Pons record or clean metadata is not an audit, a price signal, or a safety verdict. Holdings are current balances only.',
  };
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
  if (!['network','address','transaction','aeon','contributions','token'].includes(action)) throw new Error('Unknown action');
  // Only plain strings: a one-element array (?value=..&value=..) would otherwise stringify past the regex.
  if ((action === 'address' || action === 'token') && !(typeof value === 'string' && addressPattern.test(value))) throw new Error('Invalid address');
  if (action === 'transaction' && !(typeof value === 'string' && hashPattern.test(value))) throw new Error('Invalid transaction hash');
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
  if (action === 'token') {
    const code = await rpc('eth_getCode', [value, block]);
    if (code === '0x' || delegation(code)) return {...base, address: value, contract: false, delegatedTo: delegation(code)};
    return {...base, address: value, contract: true, ...(await tokenCheck(value, block))};
  }
  if (action === 'address') {
    const [balance, code, nonce] = await Promise.all([rpc('eth_getBalance',[value,block]), rpc('eth_getCode',[value,block]), rpc('eth_getTransactionCount',[value,block])]);
    return {...base, address:value, balanceWei:BigInt(balance).toString(), codeBytes:(code.length-2)/2, delegatedTo: delegation(code), nonce:Number(BigInt(nonce)), warning:'Bytecode presence is not proof of safety. Native balance only; token holdings are not indexed.'};
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