import './app.css';
import { validateBurn, validateCopies, validateGuards, guardCalldata, tokenAmount, burnPercent } from './burn';

type Watch = { address: string; label: string };

const ADDRESS = /^0x[\da-f]{40}$/i;
const TX_HASH = /^0x[\da-f]{64}$/i;
const EXAMPLE = '0x7eD598BcEf8bd9Edd8C97A195C6d13f40801EC7e';
const INSTALL = 'bin/install-skill-pack sentinelhood/robinhood-sentinel';
const STORE = 'sentinel.watch.v1';
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

const escape = (value: unknown) =>
  String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);
const short = (a: string) => `${a.slice(0, 6)}…${a.slice(-4)}`;
const eth = (wei: string) => {
  const n = BigInt(wei);
  return `${n / 10n ** 18n}.${(n % 10n ** 18n).toString().padStart(18, '0').slice(0, 6)}`;
};
const row = (k: string, v: string) => `<div><dt>${escape(k)}</dt><dd>${v}</dd></div>`;

let watches: Watch[] = [];
try {
  const stored = JSON.parse(localStorage.getItem(STORE) || '[]');
  if (Array.isArray(stored)) watches = stored.filter((x) => typeof x?.label === 'string' && ADDRESS.test(x?.address)).slice(0, 30);
} catch {
  /* Corrupt storage is ignored. */
}

// Aeon pull requests by sentinelhood. Fallback only: statuses are refreshed live from GitHub on load.
type Contribution = { pr: number; title: string; what?: string; state: 'merged' | 'open' | 'closed'; review?: 'approved' | 'changes_requested' | 'review'; when: string };
const CONTRIBUTIONS: Contribution[] = [
  { pr: 1251, title: 'feat(onchain-monitor): add reorg-safe evidence replay', what: 'Reorg-aware replay and per-chain evidence receipts for onchain-monitor.', state: 'open', review: 'changes_requested', when: '2026-10-20' },
  { pr: 1244, title: 'feat(onchain-monitor): watch wallets and contracts on Robinhood Chain', what: 'Aeon\u2019s on-chain alerts learn Robinhood Chain, with a keyless path through the public RPC.', state: 'merged', when: '2026-10-20' },
  { pr: 1243, title: 'fix(deploy-uni-hook): add Alchemy slug for Robinhood Chain', what: 'Hook deploys to Robinhood use Alchemy when a key is set, instead of always the public RPC.', state: 'merged', when: '2026-10-18' },
  { pr: 1227, title: 'docs(packs): list the Sentinel Pack', what: 'The Sentinel Pack joins Aeon\u2019s community skill-pack registry.', state: 'merged', when: '2026-10-16' },
];
const STATUS = {
  merged: ['ok', 'Merged', 'merged'], closed: ['bad', 'Closed', 'closed'],
  approved: ['ok', 'Approved', 'opened'], changes_requested: ['wait', 'Changes requested', 'opened'], review: ['wait', 'In review', 'opened'],
} as const;
function contributionRows(list: Contribution[]) {
  return list.map((c, i) => {
    const [tone, label, verb] = STATUS[c.state === 'open' ? c.review || 'review' : c.state];
    const url = `https://github.com/aeonfun/aeon/pull/${encodeURIComponent(c.pr)}`;
    return `
      <li style="--d:${i}">
        <a class="num" href="${url}" target="_blank" rel="noopener noreferrer">#${escape(c.pr)}</a>
        <div><a href="${url}" target="_blank" rel="noopener noreferrer"><code>${escape(c.title)}</code></a>${c.what ? `<p>${escape(c.what)}</p>` : ''}</div>
        <span class="state"><span class="badge ${tone}">${label}</span>${c.when ? `<small>${verb} ${escape(c.when)}</small>` : ''}</span>
      </li>`;
  }).join('');
}

const mark = `<svg class="mark" viewBox="0 0 40 40" aria-hidden="true"><path d="M20 3 37 20 20 37 3 20Z" fill="none" stroke="currentColor" stroke-width="2.6"/><path d="M20 11 29 20 20 29 11 20Z" fill="none" stroke="#f5f1e9" stroke-width="1.2"/><path d="M20 16.5 23.5 20 20 23.5 16.5 20Z" fill="currentColor"/></svg>`;
const arrow = `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 12 12 4M6 4h6v6" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>`;

document.querySelector<HTMLDivElement>('#root')!.innerHTML = `
<header class="top">
  <a class="brand" href="#" aria-label="Sentinel home">${mark}<span><strong>SENTINEL</strong><small>ROBINHOOD CHAIN · 4663</small></span></a>
  <nav aria-label="Sections" id="nav">
    <a href="#inspect" data-section>Inspect</a><a href="#watch" data-section>Watchlist</a><a href="#aeon" data-section>Aeon</a><a href="#hooks" data-section>Hooks</a><a href="#launches" data-section>Launches</a><a href="#guard" data-section>Guard</a><a href="#contrib" data-section>Contributions</a><a href="#shiplog" data-section>Log</a>
    <a href="https://x.com/sentinelhood" target="_blank" rel="noopener noreferrer">X ${arrow}</a>
    <span class="nav-ind" aria-hidden="true"></span>
  </nav>
  <div class="pill-wrap">
    <button class="pill" id="roPill" aria-expanded="false" aria-controls="roPop"><i class="dot live"></i>READ-ONLY · NO KEYS</button>
    <div class="pop" id="roPop" role="dialog" aria-label="What read-only means" aria-hidden="true">
      <strong>What read-only means here</strong>
      <ul>
        <li>No wallet connection, nothing to sign.</li>
        <li>The site only reads chain data. It never sends a transaction.</li>
        <li>Your watchlist stays in this browser.</li>
        <li>The RPC URL stays on the server.</li>
      </ul>
    </div>
  </div>
</header>

<main>
  <section class="hero">
    <div class="hero-copy">
      <p class="kicker reveal" style="--d:0">ON-CHAIN EVIDENCE · NOT A SAFETY CERTIFICATE</p>
      <h1 class="reveal" style="--d:1">Less guessing.<br><em>More evidence.</em></h1>
      <p class="lede reveal" style="--d:2">Inspect real transactions and addresses on Robinhood Chain, keep a quiet watchlist, and give your Aeon agent a keyless monitor for chain 4663. No wallet connection. Nothing to sign.</p>
      <div class="hero-cta reveal" style="--d:3"><a class="btn primary" href="#inspect">Inspect an address</a><a class="btn ghost" href="#aeon">Aeon skill pack</a></div>
    </div>

    <aside class="hero-side">
      <article class="card net reveal" style="--d:2" aria-labelledby="netTitle">
        <header class="card-head"><span id="netTitle" class="tag"><i class="dot" id="netDot"></i>NETWORK</span><button id="refresh" class="link">Refresh</button></header>
        <dl class="stats">
          <div><dt>Block</dt><dd id="statBlock">…</dd></div>
          <div><dt>Gas</dt><dd id="statGas">…</dd></div>
          <div><dt>Chain</dt><dd>4663</dd></div>
          <div><dt>Checked</dt><dd id="statTime">…</dd></div>
        </dl>
        <p id="network" class="status" role="status">Checking RPC…</p>
      </article>

      <article class="card notice reveal" style="--d:3" aria-labelledby="tokenTitle" id="tokenCard">
        <span class="tag gold" id="tokenTitle">OFFICIAL TOKEN</span>
        <div id="tokenBody">
          <p class="notice-big">Not live yet.</p>
          <p>Sentinel has no token today. Any contract address that claims to be Sentinel is not ours. Announcements come only from <a href="https://x.com/sentinelhood" target="_blank" rel="noopener noreferrer">@sentinelhood</a>.</p>
        </div>
      </article>
    </aside>
  </section>

  <section class="grid">
    <article class="card tool reveal" id="inspect" aria-labelledby="inspectTitle">
      <span class="tag gold">01 · INSPECTOR</span>
      <h2 id="inspectTitle">Read the receipt.</h2>
      <p class="muted">Paste an address (42 characters) or a transaction hash (66 characters). This reads what already happened on chain. It does not simulate a transaction.</p>
      <form id="inspectForm" class="field">
        <label for="lookup">Address or transaction hash</label>
        <div class="input-row"><input id="lookup" required maxlength="66" placeholder="0x…" autocomplete="off" spellcheck="false"><button class="btn primary">Inspect</button></div>
      </form>
      <button class="link" id="example">Try the Pons factory address</button>
      <div id="inspection" class="result" aria-live="polite"></div>
    </article>

    <article class="card tool reveal" id="watch" aria-labelledby="watchTitle">
      <span class="tag gold">02 · WATCHLIST</span>
      <h2 id="watchTitle">Keep a quiet eye.</h2>
      <p class="muted">Saved only in this browser. Native ETH balances are read when you ask. No background alerts, no prices.</p>
      <form id="watchForm" class="field two">
        <div><label for="watchLabel">Label</label><input id="watchLabel" required maxlength="40" placeholder="Treasury"></div>
        <div><label for="watchAddress">Address</label><input id="watchAddress" required pattern="0x[0-9a-fA-F]{40}" maxlength="42" placeholder="0x…" spellcheck="false"></div>
        <button class="btn primary">Save address</button>
      </form>
      <p id="watchStatus" class="hint" role="status"></p>
      <ul id="watchRows" class="watchlist"></ul>
      <button class="link" id="export">Export as an Aeon monitoring brief</button>
    </article>
  </section>

  <section class="card launches reveal" id="launches" aria-labelledby="launchesTitle">
    <div class="launch-head">
      <div>
        <span class="tag gold"><i class="dot live"></i>LIVE · PONS V2 FACTORY</span>
        <h2 id="launchesTitle">New launches, as they land.</h2>
        <p class="muted">The newest tokens created through the Pons v2 factory on Robinhood Chain, with the creator tax and phase read from the factory itself. Tap <b>Check</b> for the full read.</p>
      </div>
      <button class="link" id="launchRefresh">Refresh</button>
    </div>
    <ul class="launch-list" id="launchList" aria-live="polite"><li class="hint">Reading the factory…</li></ul>
    <p class="hint" id="launchMeta"></p>
    <p class="links"><a href="/skills/pons-launch-watch.md" target="_blank" rel="noopener">Get alerted when your ticker is copied: Aeon skill ${arrow}</a></p>
  </section>

  <section class="card guard reveal" id="guard" aria-labelledby="guardTitle">
    <span class="tag gold">SENTINEL GUARD · BURN SNTL</span>
    <h2 id="guardTitle">Guard your ticker.</h2>
    <p class="muted">Launched on Pons? Burn <b>1,000,000 SNTL</b> from your <b>deployer wallet</b> with your token address attached, and Sentinel lists every Pons launch that copies your ticker or name, for 30 days, on a public page. The SNTL is destroyed: nobody receives it, including us. Each extra burn adds 30 days.</p>
    <form id="guardForm" class="field">
      <label for="guardToken">Your Pons token address</label>
      <div class="input-row"><input id="guardToken" required pattern="0x[0-9a-fA-F]{40}" maxlength="42" placeholder="0x…" spellcheck="false" autocomplete="off"><button class="btn primary">Build the burn</button></div>
    </form>
    <div id="guardHow" class="result" aria-live="polite"></div>
    <ul class="copy-list guard-list" id="guardList" aria-live="polite"><li class="hint">Loading guarded tokens…</li></ul>
    <p class="hint" id="guardMeta"></p>
    <p class="hint">A guard is a public alert, not protection: copies can still launch. It only counts when the burn is sent by the deployer the Pons factory records for that token. Check the result here before you announce it.</p>
  </section>

  <section class="card aeon reveal" id="aeon" aria-labelledby="aeonTitle">
    <div class="aeon-main">
      <span class="tag gold">03 · AEON</span>
      <h2 id="aeonTitle">The gap it fills.</h2>
      <p class="muted">Aeon\u2019s <code>onchain-monitor</code> now includes the Robinhood Chain path from merged PR <a href="https://github.com/aeonfun/aeon/pull/1244" target="_blank" rel="noopener noreferrer">#1244</a>. It watches addresses for nonce, balance and bytecode changes, reads only from the official RPC, and needs no keys.</p>
      <div class="cmd"><code id="installCmd">${INSTALL}</code><button class="btn small" id="copyCmd">Copy</button></div>
      <p class="links"><a href="https://github.com/sentinelhood/robinhood-sentinel" target="_blank" rel="noopener noreferrer">Source ${arrow}</a><a href="/skills/robinhood-chain-monitor.md" target="_blank" rel="noopener">SKILL.md ${arrow}</a><a href="/openapi.json" target="_blank" rel="noopener">OpenAPI ${arrow}</a><a href="/llms.txt" target="_blank" rel="noopener">llms.txt ${arrow}</a></p>
    </div>
    <div class="aeon-search">
      <form id="aeonForm" class="field">
        <label for="query">Search Aeon docs and skills</label>
        <div class="input-row"><input id="query" required minlength="2" maxlength="200" value="onchain monitor"><button class="btn primary">Search</button></div>
      </form>
      <ul id="aeonResults" class="results" aria-live="polite"></ul>
      <p class="hint">Results come live from aeon.fun/ask. To run an agent, <a href="https://www.aeon.fun/connect" target="_blank" rel="noopener noreferrer">sign in to Aeon Connect</a> with your own repo and model.</p>
    </div>
  </section>

  <section class="card hooks reveal" id="hooks" aria-labelledby="hooksTitle">
    <div class="hooks-head">
      <div>
        <span class="tag gold">04 · HOOK USAGE</span>
        <h2 id="hooksTitle">Which Aeon hooks get used?</h2>
        <p class="muted">Every Uniswap v4 pool on Robinhood Chain whose hook is in Aeon's <a href="https://github.com/aeonfun/univ4-hooks" target="_blank" rel="noopener noreferrer">univ4-hooks</a> registry, counted from the official RPC by the <code>hook-usage</code> skill.</p>
      </div>
      <dl class="stats hook-stats" id="hookStats">
        <div><dt>Hooks with pools</dt><dd>…</dd></div>
        <div><dt>Pools</dt><dd>…</dd></div>
        <div><dt>Swaps</dt><dd>…</dd></div>
      </dl>
    </div>
    <ul class="bars" id="hookBars" aria-live="polite"><li class="hint">Loading the latest snapshot…</li></ul>
    <p class="hint" id="hookMeta"></p>
    <p class="links"><a href="/hook-usage.json" target="_blank" rel="noopener">Raw JSON ${arrow}</a><a href="/skills/hook-usage.md" target="_blank" rel="noopener">SKILL.md ${arrow}</a></p>
  </section>

  <section class="card contrib reveal" id="contrib" aria-labelledby="contribTitle">
    <span class="tag gold">05 · AEON CONTRIBUTIONS</span>
    <h2 id="contribTitle">Shipped upstream.</h2>
    <p class="muted">Pull requests from <code>sentinelhood</code> to <a href="https://github.com/aeonfun/aeon" target="_blank" rel="noopener noreferrer">aeonfun/aeon</a>. Each one is public: open the link and check the review, the diff and the merge yourself.</p>
    <ul class="contrib-list" id="contribList" aria-live="polite">${contributionRows(CONTRIBUTIONS)}
    </ul>
    <p class="hint" id="contribMeta">Showing saved statuses. Checking GitHub…</p>
  </section>

  <section class="card shiplog reveal" id="shiplog" aria-labelledby="shiplogTitle">
    <span class="tag gold">SHIPPING LOG</span>
    <h2 id="shiplogTitle">What changed, and when.</h2>
    <p class="muted">Read from this site’s public <a href="https://github.com/sentinelhood/robinhood-sentinel/commits/main" target="_blank" rel="noopener noreferrer">commit history</a>. Every line links to the exact change.</p>
    <ol class="ship-list" id="shipList" aria-live="polite"><li class="hint">Reading GitHub…</li></ol>
    <p class="hint" id="shipMeta"></p>
  </section>
</main>

<footer class="foot">
  <span>${mark}Read-only · Server-side RPC · No funds moved</span>
  <span><a href="https://x.com/sentinelhood" target="_blank" rel="noopener noreferrer">@sentinelhood</a><a href="https://github.com/sentinelhood/robinhood-sentinel" target="_blank" rel="noopener noreferrer">GitHub</a><a href="https://www.aeon.fun/developers" target="_blank" rel="noopener noreferrer">Aeon docs</a></span>
</footer>`;

const el = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const value = (id: string) => el<HTMLInputElement>(id).value.trim();

async function api(action: string, v = '') {
  const response = await fetch(`/api/service?action=${action}&value=${encodeURIComponent(v)}`, { signal: AbortSignal.timeout(30000) });
  if (!(response.headers.get('content-type') || '').includes('application/json')) throw new Error('API not available. Use the Vercel deployment or vercel dev.');
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed');
  return data;
}

function busy(card: HTMLElement, on: boolean) {
  card.classList.toggle('is-loading', on);
}

function show(target: HTMLElement, html: string) {
  target.innerHTML = html;
  target.classList.remove('appear');
  void target.offsetWidth;
  target.classList.add('appear');
}

// Animate a number change (block height) without fighting reduced-motion users.
function countTo(node: HTMLElement, next: number) {
  const prev = Number(node.dataset.n || 0);
  node.dataset.n = String(next);
  if (reduceMotion || !prev || prev === next || Math.abs(next - prev) > 5000) {
    node.textContent = next.toLocaleString();
  } else {
    const start = performance.now();
    const step = (t: number) => {
      const k = Math.min(1, (t - start) / 700);
      node.textContent = Math.round(prev + (next - prev) * (1 - (1 - k) ** 3)).toLocaleString();
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  node.classList.remove('tick');
  void node.offsetWidth;
  node.classList.add('tick');
}

async function network() {
  const button = el<HTMLButtonElement>('refresh');
  button.disabled = true;
  try {
    const data = await api('network');
    countTo(el('statBlock'), data.block);
    el('statGas').textContent = `${(Number(data.gasPriceWei) / 1e9).toFixed(3)} gwei`;
    el('statTime').textContent = new Date(data.checkedAt).toLocaleTimeString();
    el('network').textContent = 'Live. Chain ID verified as 4663 on this read.';
    el('netDot').className = 'dot live';
  } catch (e) {
    el('network').textContent = `Unavailable: ${(e as Error).message}`;
    el('netDot').className = 'dot down';
  } finally {
    button.disabled = false;
  }
}

el('refresh').addEventListener('click', network);
el('example').addEventListener('click', () => {
  el<HTMLInputElement>('lookup').value = EXAMPLE;
  el<HTMLInputElement>('lookup').focus();
});

el('inspectForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const v = value('lookup');
  const out = el('inspection');
  const action = ADDRESS.test(v) ? 'address' : TX_HASH.test(v) ? 'transaction' : '';
  if (!action) return show(out, '<p class="error">Enter a valid 0x address (42 characters) or transaction hash (66 characters).</p>');
  // A token result sets ?ca=; any other lookup must not leave a stale share link in the address bar.
  if (location.search) history.replaceState(null, '', location.pathname + location.hash);
  const card = el('inspect');
  const button = el('inspectForm').querySelector('button')!;
  button.disabled = true;
  busy(card, true);
  show(out, '<p class="hint">Reading chain…</p>');
  // Start the token and deployer reads now, alongside the address read, instead of after it.
  // Wallets answer both cheaply (no contract / no Pons record) and the results are simply unused.
  const prefetch = action === 'address' ? { token: api('token', v), deployer: api('deployer', v) } : undefined;
  prefetch?.token.catch(() => {}); prefetch?.deployer.catch(() => {});
  try {
    const data = await api(action, v);
    const link = `<a class="link-out" href="https://robinhoodchain.blockscout.com/${action === 'address' ? 'address' : 'tx'}/${v}" target="_blank" rel="noopener noreferrer">Open in Blockscout ${arrow}</a>`;
    if (action === 'address') {
      const delegated = typeof data.delegatedTo === 'string' && ADDRESS.test(data.delegatedTo);
      const kind = delegated ? 'Wallet · 7702' : data.codeBytes ? 'Contract' : 'Account';
      const code = delegated ? row('Delegates to', escape(short(data.delegatedTo))) : row('Bytecode', `${escape(Number(data.codeBytes).toLocaleString())} bytes`);
      show(out, `<h3><span class="badge">${kind}</span>${escape(short(v))}</h3><dl class="kv">${row('Balance', `${escape(eth(data.balanceWei))} ETH`)}${code}${row('Nonce', escape(data.nonce))}${row('Read at block', escape(Number(data.block).toLocaleString()))}</dl><div id="tokenCheck"></div><p class="hint">${escape(data.warning)}</p>${link}`);
      if (data.codeBytes && !delegated) void tokenCheck(v, prefetch);
    } else if (!data.transaction) {
      show(out, '<p class="error">Transaction not found on chain 4663. Check the hash, or retry if it was just submitted.</p>');
    } else {
      const tx = data.transaction;
      const r = data.receipt;
      const state = r ? (r.status === '0x1' ? ['ok', 'Succeeded'] : ['bad', 'Reverted']) : ['wait', 'Pending'];
      show(out, `<h3><span class="badge ${state[0]}">${state[1]}</span>${escape(short(v))}</h3><dl class="kv">${row('From', escape(short(tx.from)))}${row('To', escape(tx.to ? short(tx.to) : 'Contract creation'))}${row('Value', `${escape(eth(BigInt(tx.value).toString()))} ETH`)}${row('Gas used', escape(r ? BigInt(r.gasUsed).toLocaleString() : 'Pending'))}</dl><details><summary>Raw transaction and receipt</summary><pre>${escape(JSON.stringify(data, null, 2))}</pre></details><p class="hint">${escape(data.warning)}</p>${link}`);
    }
  } catch (e) {
    show(out, `<p class="error">${escape((e as Error).message)}</p>`);
  } finally {
    button.disabled = false;
    busy(card, false);
  }
});

// How many Pons tokens this token's deployer has launched, and which one this is. Facts, not a verdict.
async function deployerHistory(token: string, pending?: Promise<any>) {
  const cell = document.getElementById('deployerHistory');
  if (!cell) return;
  try {
    const d = await (pending || api('deployer', token));
    if (el<HTMLInputElement>('lookup').value.trim().toLowerCase() !== token.toLowerCase()) return;
    if (!d.pons || !Number.isSafeInteger(d.launches) || d.launches < 1) throw new Error('none');
    const since = d.firstAt ? new Date(d.firstAt).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : '';
    const nth = Number.isSafeInteger(d.launchNumber) ? `This is launch #${Number(d.launchNumber).toLocaleString()}` : '';
    cell.innerHTML = d.launches === 1
      ? '<b>First Pons launch</b> <small>from this address</small>'
      : `<b>${escape(Number(d.launches).toLocaleString())} Pons launches</b> <small>${since ? `since ${escape(since)}` : ''}${nth ? ` · ${escape(nth)}` : ''}</small>${d.launches >= 10 ? ' <span class="badge wait">Serial deployer</span>' : ''}`;
  } catch {
    cell.innerHTML = '<span class="hint">History unavailable right now</span>';
  }
}

const shareLink = (address: string) => `${location.origin}/?ca=${address}`;
async function copyText(button: HTMLButtonElement, text: string, fallback: HTMLElement) {
  try { await navigator.clipboard.writeText(text); button.textContent = 'Copied'; } catch { getSelection()?.selectAllChildren(fallback); button.textContent = 'Press Ctrl+C'; }
  setTimeout(() => (button.textContent = 'Copy link'), 1600);
}
// Open the Inspector on an address: used by ?ca= share links and the launch feed's Check buttons.
function inspectAddress(address: string) {
  el<HTMLInputElement>('lookup').value = address;
  el<HTMLFormElement>('inspectForm').requestSubmit();
  el('inspect').scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
}

// Token check: ERC-20 metadata + the Pons v2 factory record for this address. Facts only, no verdict.
const PHASE = ['Bonding curve', 'Swept · pool pending', 'Uniswap v4 · liquidity locked', 'Rescued (recovery path)'];
const bps = (n: unknown) => (Number.isSafeInteger(n) ? `${(Number(n) / 100).toFixed(2).replace(/\.?0+$/, '')}%` : '—');
async function tokenCheck(address: string, pending?: { token: Promise<any>; deployer: Promise<any> }) {
  const box = el('tokenCheck');
  box.innerHTML = '<p class="hint">Checking token and Pons launch record…</p>';
  try {
    const d = await (pending?.token || api('token', address));
    if (el<HTMLInputElement>('lookup').value.trim().toLowerCase() !== address.toLowerCase()) return;
    if (!d.erc20) { box.innerHTML = '<p class="hint">Not an ERC-20 token (no decimals/totalSupply).</p>'; return; }
    const p = d.pons;
    const head = `<h4 class="tc-head"><span class="tag gold">TOKEN</span>${escape(d.name || 'Unnamed')} <code>${escape(d.symbol || '?')}</code></h4>`;
    const meta = row('Total supply', escape(d.totalSupply)) + row('Decimals', escape(d.decimals));
    if (!p) {
      box.innerHTML = `${head}<dl class="kv">${meta}${row('Pons v2 launch', '<span class="badge">No record</span>')}</dl><p class="hint">Not launched through the Pons v2 factory. Tax, supply rules and liquidity are not covered by Pons guarantees. Read the contract itself.</p>`;
      return;
    }
    const total = Number.isSafeInteger(p.baseFeeBps) ? bps(p.baseFeeBps + p.creatorTaxBps) : '—';
    const phase = PHASE[p.phase] || `Unknown (${escape(p.phase)})`;
    const holders = (Array.isArray(p.holders) ? p.holders : []).map((h: { role: string; address: string; balance: string | null; percent: string | null }) =>
      row(`${escape(h.role)} holds`, h.balance === null ? 'unreadable' : `${escape(h.balance)} <small>(${escape(h.percent)}%)</small>`)).join('');
    box.innerHTML = `${head}<dl class="kv">
      ${row('Pons v2 launch', `<span class="badge ok">Factory record</span>`)}
      ${row('Phase', escape(phase))}
      ${row('Trading cost', `${escape(total)} <small>(${escape(bps(p.baseFeeBps))} base + ${escape(bps(p.creatorTaxBps))} creator tax)</small>`)}
      ${row('Buyback', p.buybackEnabled ? 'On' : 'Off')}
      ${row('Pair', p.pairToken === '0x' + '0'.repeat(40) ? 'Native ETH' : `<code>${escape(short(p.pairToken))}</code>`)}
      ${row('Deployer', `<a href="https://robinhoodchain.blockscout.com/address/${escape(p.deployer)}" target="_blank" rel="noopener noreferrer">${escape(short(p.deployer))}</a>`)}
      <div><dt>Deployer history</dt><dd id="deployerHistory"><span class="hint">Reading every Pons launch…</span></dd></div>
      <div><dt>Sentinel Guard</dt><dd id="guardStatus"><span class="hint">Checking…</span></dd></div>
      ${holders}${meta}
    </dl><p class="hint">Tax is fixed at launch and cannot be raised. ${p.phase === 2 ? 'Pool liquidity is locked by the Pons locker. ' : ''}${escape(d.warning)}</p>
    <div class="cmd share"><code id="shareUrl">${escape(shareLink(address))}</code><button class="btn small" id="copyShare">Copy link</button></div>`;
    history.replaceState(null, '', `/?ca=${address}`);
    void deployerHistory(address, pending?.deployer);
    void guardStatus(address);
    el('copyShare').addEventListener('click', () => copyText(el<HTMLButtonElement>('copyShare'), shareLink(address), el('shareUrl')));
  } catch (e) {
    box.innerHTML = `<p class="error">Token check unavailable: ${escape((e as Error).message)}</p>`;
  }
}

function renderWatch() {
  el('watchRows').innerHTML =
    watches
      .map(
        (w, i) => `<li class="watch-entry"><div class="who"><strong>${escape(w.label)}</strong><code title="${escape(w.address)}">${escape(short(w.address))}</code></div><span class="bal" id="balance${i}">—</span><div class="acts"><button class="btn small" data-check="${i}">Read</button><button class="btn small ghost" data-remove="${i}" aria-label="Remove ${escape(w.label)}">Remove</button></div></li>`,
      )
      .join('') || '<li class="empty">No watched addresses yet.</li>';
}

function saveWatch(next: Watch[], message: string) {
  try {
    localStorage.setItem(STORE, JSON.stringify(next));
    watches = next;
    renderWatch();
    el('watchStatus').textContent = message;
  } catch {
    el('watchStatus').textContent = 'Storage is unavailable, so this was not saved.';
  }
}

el('watchForm').addEventListener('submit', (e) => {
  e.preventDefault();
  const address = value('watchAddress');
  if (!ADDRESS.test(address)) return;
  if (watches.length >= 30) return void (el('watchStatus').textContent = 'The watchlist holds up to 30 addresses.');
  if (watches.some((w) => w.address.toLowerCase() === address.toLowerCase())) return void (el('watchStatus').textContent = 'That address is already on the watchlist.');
  saveWatch([...watches, { address, label: value('watchLabel') }], 'Saved in this browser.');
  el<HTMLFormElement>('watchForm').reset();
});

el('watchRows').addEventListener('click', async (e) => {
  const button = (e.target as HTMLElement).closest('button');
  if (!button) return;
  if (button.dataset.remove !== undefined) return saveWatch(watches.filter((_, i) => i !== Number(button.dataset.remove)), 'Removed.');
  const i = Number(button.dataset.check);
  const address = watches[i]?.address;
  if (!address) return;
  const output = el(`balance${i}`);
  button.disabled = true;
  output.textContent = 'Reading…';
  try {
    const d = await api('address', address);
    output.innerHTML = `${escape(eth(d.balanceWei))} ETH<small>block ${escape(Number(d.block).toLocaleString())}</small>`;
    output.classList.remove('appear');
    void output.offsetWidth;
    output.classList.add('appear');
  } catch (err) {
    output.textContent = (err as Error).message;
  } finally {
    button.disabled = false;
  }
});

el('export').addEventListener('click', () => {
  const text = `# Robinhood Chain monitoring brief\n\nChain ID: 4663\nPublic RPC: https://rpc.mainnet.chain.robinhood.com\n\nRead-only monitoring request for an Aeon operator. Install the Sentinel Pack (${INSTALL}) and copy these into memory/robinhood-watches.yml. Report the block with each observation. Do not sign or broadcast transactions. No agent is activated by this export.\n\nWatched addresses:\n${watches.map((w) => `${w.address} (${w.label})`).join('\n')}\n`;
  const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = 'robinhood-monitoring-brief.md';
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

el('copyCmd').addEventListener('click', async () => {
  const button = el<HTMLButtonElement>('copyCmd');
  try {
    await navigator.clipboard.writeText(INSTALL);
    button.textContent = 'Copied';
  } catch {
    getSelection()?.selectAllChildren(el('installCmd'));
    button.textContent = 'Press Ctrl+C';
  }
  setTimeout(() => (button.textContent = 'Copy'), 1600);
});

el('aeonForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const button = el('aeonForm').querySelector('button')!;
  const out = el('aeonResults');
  button.disabled = true;
  busy(el('aeon'), true);
  show(out, '<li class="hint">Searching aeon.fun…</li>');
  try {
    const d = await api('aeon', value('query'));
    show(
      out,
      d.results
        .map(
          (r: { url: string; name: string; description: string }, i: number) =>
            `<li style="--d:${i}"><a href="${escape(r.url)}" target="_blank" rel="noopener noreferrer">${escape(r.name.replace(/^Skill:\s*/, ''))} ${arrow}</a><p>${escape(r.description)}</p></li>`,
        )
        .join('') || '<li class="hint">No matching resources.</li>',
    );
  } catch (err) {
    show(out, `<li class="error">${escape((err as Error).message)}</li>`);
  } finally {
    button.disabled = false;
    busy(el('aeon'), false);
  }
});

// Reveal-on-scroll. Elements already in view animate in immediately with their stagger.
const io = 'IntersectionObserver' in window && !reduceMotion
  ? new IntersectionObserver((entries) => entries.forEach((en) => en.isIntersecting && (en.target.classList.add('in'), io?.unobserve(en.target))), { rootMargin: '0px 0px -8% 0px' })
  : null;
document.querySelectorAll('.reveal').forEach((n) => (io ? io.observe(n) : n.classList.add('in')));

// ---------- navigation: eased scroll, active indicator, arrival flash ----------
const header = document.querySelector<HTMLElement>('.top')!;
const nav = el('nav');
const indicator = nav.querySelector<HTMLElement>('.nav-ind')!;
const sectionLinks = [...nav.querySelectorAll<HTMLAnchorElement>('a[data-section]')];
let scrollAnim = 0;

const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);

function moveIndicator(link: HTMLAnchorElement | null, instant = false) {
  sectionLinks.forEach((a) => a.classList.toggle('active', a === link));
  if (!link) return void indicator.classList.remove('on');
  // On first placement (and on resize) jump without sliding, so a refresh
  // doesn't show the bar gliding across the header from the left edge.
  if (instant) {
    indicator.classList.add('instant');
    indicator.style.width = `${link.offsetWidth - 24}px`;
    indicator.style.transform = `translateX(${link.offsetLeft + 12}px)`;
    indicator.classList.add('on');
    void indicator.offsetWidth;
    indicator.classList.remove('instant');
    return;
  }
  indicator.style.width = `${link.offsetWidth - 24}px`;
  indicator.style.transform = `translateX(${link.offsetLeft + 12}px)`;
  indicator.classList.add('on');
  // On mobile the nav scrolls sideways: keep the active item in view.
  if (nav.scrollWidth > nav.clientWidth) nav.scrollTo({ left: link.offsetLeft - 24, behavior: reduceMotion ? 'auto' : 'smooth' });
}

function flash(target: HTMLElement) {
  if (!target.classList.contains('card')) return;
  target.classList.remove('flash');
  void target.offsetWidth;
  target.classList.add('flash');
}

// Web fonts load without blocking render, so document.fonts.ready can resolve before
// the font stylesheet is even applied (nothing is pending yet). Real readiness is: the
// stylesheet is in place, layout has used it once, and the faces it asked for loaded.
const fontsReady: Promise<void> = (async () => {
  const link = document.querySelector<HTMLLinkElement>('link[href*="fonts.googleapis.com/css2"]');
  if (link) {
    await new Promise<void>((resolve) => {
      const timer = window.setInterval(() => { if (link.rel === 'stylesheet' && link.sheet) finish(); }, 50);
      const giveUp = window.setTimeout(() => finish(), 6000);
      function finish() { clearInterval(timer); clearTimeout(giveUp); resolve(); }
      link.addEventListener('error', finish, { once: true });
    });
  }
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  await document.fonts?.ready;
})();
let fontsDone = false;
void fontsReady.then(() => { fontsDone = true; });

// Document-space top of an element, from layout only. getBoundingClientRect() includes
// CSS transforms, and cards still sliding in (translateY on .reveal) would read up to
// 14px off; offsetTop ignores transforms, so every landing uses the settled layout.
function docTop(node: HTMLElement) {
  let y = 0;
  for (let n: HTMLElement | null = node; n; n = n.offsetParent as HTMLElement | null) y += n.offsetTop;
  return y;
}

function glideTo(target: HTMLElement) {
  // Recomputed every frame, so a layout shift mid-glide (font swap, live data) still ends on target.
  const goal = () => (target === document.body ? 0 : Math.max(0, docTop(target) - header.offsetHeight - 16));
  const anchor = target === document.body ? { anchor: 'top', offset: 0 } : { anchor: `#${target.id}`, offset: -16 };
  const land = () => {
    flash(target);
    // If fonts are still on their way, hold this landing until they swap in.
    if (!fontsDone) settleOn(anchor);
  };
  const from = scrollY;
  const distance = goal() - from;
  cancelAnimationFrame(scrollAnim);
  if (reduceMotion || Math.abs(distance) < 2) {
    scrollTo(0, goal());
    return land();
  }
  const duration = Math.min(900, Math.max(420, Math.abs(distance) * 0.45));
  const start = performance.now();
  const step = (now: number) => {
    const k = Math.min(1, (now - start) / duration);
    scrollTo(0, from + (goal() - from) * easeInOut(k));
    if (k < 1) scrollAnim = requestAnimationFrame(step);
    else land();
  };
  scrollAnim = requestAnimationFrame(step);
}
// After a nav click the chosen item stays active (Inspect and Watchlist sit side by side,
// so position alone can't tell them apart) until the user scrolls by hand.
let lockedLink: HTMLAnchorElement | null = null;
// A wheel, touch or key from the user always wins over an in-flight glide.
// Once they scroll by hand, an old #section in the URL no longer describes where
// they are, so drop it (otherwise a refresh would yank them back to that section).
['wheel', 'touchstart', 'keydown'].forEach((ev) =>
  addEventListener(ev, () => {
    cancelAnimationFrame(scrollAnim);
    lockedLink = null;
    if (location.hash) history.replaceState(null, '', location.pathname + location.search);
  }, { passive: true }),
);

document.addEventListener('click', (e) => {
  const link = (e.target as HTMLElement).closest<HTMLAnchorElement>('a[href^="#"]');
  if (!link) return;
  stopSettle?.();
  const id = link.getAttribute('href')!.slice(1);
  const target = id ? document.getElementById(id) : null;
  e.preventDefault();
  if (!target) {
    lockedLink = null;
    history.replaceState(null, '', location.pathname);
    moveIndicator(null);
    return glideTo(document.body);
  }
  const navLink = sectionLinks.find((a) => a.getAttribute('href') === `#${id}`) ?? null;
  lockedLink = navLink;
  moveIndicator(navLink);
  history.replaceState(null, '', `#${id}`);
  glideTo(target);
});

// Scroll-spy: the active section is the last one whose top has passed the header.
let spyQueued = false;
function spy(instant = false) {
  spyQueued = false;
  header.classList.toggle('scrolled', scrollY > 8);
  if (lockedLink) return;
  const line = header.offsetHeight + innerHeight * 0.3;
  let current: HTMLAnchorElement | null = null;
  for (const a of sectionLinks) {
    const s = document.querySelector(a.getAttribute('href')!);
    if (s && s.getBoundingClientRect().top <= line) current = a;
  }
  if (innerHeight + scrollY >= document.documentElement.scrollHeight - 4) current = sectionLinks[sectionLinks.length - 1];
  if (current !== sectionLinks.find((a) => a.classList.contains('active'))) moveIndicator(current, instant);
}
addEventListener('scroll', () => { if (!spyQueued) { spyQueued = true; requestAnimationFrame(() => spy()); } }, { passive: true });
addEventListener('resize', () => moveIndicator(sectionLinks.find((a) => a.classList.contains('active')) ?? null, true));

// ---------- read-only popover ----------
const pill = el<HTMLButtonElement>('roPill');
const pop = el('roPop');
function setPop(open: boolean) {
  pill.setAttribute('aria-expanded', String(open));
  pop.setAttribute('aria-hidden', String(!open));
  pop.classList.toggle('open', open);
}
pill.addEventListener('click', (e) => { e.stopPropagation(); setPop(!pop.classList.contains('open')); });
document.addEventListener('click', (e) => { if (!pop.contains(e.target as Node)) setPop(false); });
addEventListener('keydown', (e) => { if (e.key === 'Escape') { setPop(false); pill.focus(); } });

// ---------- precise scroll restore on refresh ----------
// The position is saved relative to the nearest section ("12px into #watch"), not as a
// raw scrollY. Web fonts and live data change heights after load, so a raw pixel value
// lands in the wrong place; an anchor + offset still points at the same content.
const ANCHORS = ['.hero', '#inspect', '#watch', '#launches', '#guard', '#aeon', '#hooks', '#contrib', '#shiplog', '.foot'];
const SCROLL_KEY = 'sentinel.scroll.v1';
type Saved = { path: string; anchor: string; offset: number };

if ('scrollRestoration' in history) history.scrollRestoration = 'manual';

function currentAnchor(): Saved {
  const line = header.offsetHeight;
  let best: { anchor: string; top: number } = { anchor: '.hero', top: -Infinity };
  for (const sel of ANCHORS) {
    const node = document.querySelector<HTMLElement>(sel);
    if (!node) continue;
    const top = docTop(node) - scrollY;
    // The last anchor whose top is at or above the header line is the one being read.
    if (top <= line + 1 && top > best.top) best = { anchor: sel, top };
  }
  if (best.top === -Infinity) best = { anchor: '.hero', top: docTop(document.querySelector<HTMLElement>('.hero')!) - scrollY };
  return { path: location.pathname, anchor: best.anchor, offset: Math.round(line - best.top) };
}

let restoring = false;
let saveQueued = false;
function saveScroll() {
  saveQueued = false;
  if (restoring) return;
  try { sessionStorage.setItem(SCROLL_KEY, JSON.stringify(scrollY < 2 ? { path: location.pathname, anchor: 'top', offset: 0 } : currentAnchor())); } catch { /* storage unavailable */ }
}
addEventListener('scroll', () => { if (!saveQueued) { saveQueued = true; requestAnimationFrame(saveScroll); } }, { passive: true });
addEventListener('pagehide', saveScroll);

function applyAnchor(target: { anchor: string; offset: number }) {
  if (target.anchor === 'top') return scrollTo(0, 0);
  const node = document.querySelector<HTMLElement>(target.anchor);
  if (!node) return;
  scrollTo(0, Math.max(0, docTop(node) - header.offsetHeight + target.offset));
}

// Apply now, then re-apply whenever layout shifts (fonts swap in, live data fills),
// until fonts are ready AND the layout has been still for 400ms, or the user takes
// over. Anchor-relative re-applies keep the same content in view, so a late font swap
// (or a page that was too short to scroll that far) still ends on the saved spot.
let stopSettle: (() => void) | null = null;
function settleOn(target: { anchor: string; offset: number }) {
  stopSettle?.();
  restoring = true;
  const apply = () => { applyAnchor(target); spy(true); };
  let stopped = false;
  let fontsSettled = fontsDone;
  let quiet = 0;
  const inputs = ['wheel', 'touchstart', 'keydown', 'pointerdown'];
  const stop = () => {
    if (stopped) return;
    stopped = true; restoring = false; ro.disconnect(); clearTimeout(quiet); clearTimeout(cap);
    inputs.forEach((ev) => removeEventListener(ev, stop));
    if (stopSettle === stop) stopSettle = null;
  };
  stopSettle = stop;
  const armQuiet = () => { clearTimeout(quiet); if (fontsSettled) quiet = window.setTimeout(stop, 400); };
  const ro = new ResizeObserver(() => { if (!stopped) { apply(); armQuiet(); } });
  inputs.forEach((ev) => addEventListener(ev, stop, { passive: true }));
  apply();
  ro.observe(document.body);
  void fontsReady.then(() => { fontsSettled = true; if (!stopped) { apply(); armQuiet(); } });
  armQuiet();
  const cap = window.setTimeout(stop, 8000);
}

// ---------- hook usage (static snapshot, refreshed by scripts/snapshot-hook-usage.sh) ----------
type HookRow = { hook: string; pools: number; activePools: number; swaps: number; uniqueSenders: number };
async function loadHookUsage() {
  const bars = el('hookBars');
  try {
    const r = await (await fetch('/hook-usage.json', { signal: AbortSignal.timeout(15000) })).json();
    if (r.chainId !== 4663 || !Array.isArray(r.hooks)) throw new Error('bad snapshot');
    const t = r.totals;
    const dd = el('hookStats').querySelectorAll('dd');
    dd[0].textContent = `${t.hooksWithPools}/${t.hooks}`;
    dd[1].textContent = Number(t.pools).toLocaleString();
    dd[2].textContent = `${Number(t.swaps).toLocaleString()} / ${r.windowDays}d`;
    const rows: HookRow[] = [...r.hooks].sort((a: HookRow, b: HookRow) => b.pools - a.pools || a.hook.localeCompare(b.hook));
    const max = Math.max(1, ...rows.map((x) => x.pools));
    bars.innerHTML = rows
      .map((x, i) => `<li class="${x.pools ? 'on' : 'off'}" style="--d:${i};--w:${(x.pools / max) * 100}%">
        <span class="name">${escape(x.hook)}</span>
        <span class="track"><i></i></span>
        <span class="num">${x.pools}</span>
        <span class="sub">${x.pools ? `${x.activePools} active · ${x.swaps} swaps` : 'no pools yet'}</span>
      </li>`)
      .join('');
    const when = r.generatedAt ? new Date(r.generatedAt).toLocaleString() : '';
    el('hookMeta').textContent = `Read at block ${Number(r.block).toLocaleString()}${when ? ` · ${when}` : ''}. Pools = v4 Initialize events naming the hook. Callers are usually routers, not people. Not a quality score.`;
  } catch {
    bars.innerHTML = '<li class="error">Snapshot unavailable. Run the hook-usage skill to read it yourself.</li>';
  }
}

// ---------- official token panel (driven by /token.json) ----------
// The site only shows a contract address when token.json says live AND the address
// has bytecode on chain 4663 right now. Anything else falls back to "not live".
type TokenInfo = { live: boolean; name?: string; symbol?: string; address?: string; chainId?: number; announcement?: string; launchpad?: string };
async function loadToken() {
  let info: TokenInfo;
  try {
    info = await (await fetch(`/token.json?t=${Date.now()}`, { cache: 'no-store', signal: AbortSignal.timeout(10000) })).json();
  } catch {
    return;
  }
  if (!info.live) return;
  const body = el('tokenBody');
  const ca = info.address || '';
  const announcementOk = info.announcement === undefined || (typeof info.announcement === 'string' && /^https:\/\/(x|twitter)\.com\/sentinelhood\/status\/\d+$/.test(info.announcement));
  const source = info.announcement || 'https://x.com/sentinelhood';
  const sourceLabel = info.announcement ? 'announcement' : '@sentinelhood';
  if (!ADDRESS.test(ca) || info.chainId !== 4663 || !announcementOk) {
    body.innerHTML = '<p class="notice-big">Not live yet.</p><p class="error">The token config is incomplete, so no address is shown. Trust only announcements from @sentinelhood.</p>';
    return;
  }
  body.innerHTML = '<p class="hint">Verifying the contract on chain…</p>';
  try {
    const d = await api('address', ca);
    if (!d.codeBytes) throw new Error('no bytecode');
    body.innerHTML = `
      <p class="notice-big">${escape(info.symbol || 'Live')} <span class="badge ok">verified on chain</span></p>
      <div class="cmd"><code id="tokenCa" title="${escape(ca)}">${escape(ca)}</code><button class="btn small" id="copyCa">Copy</button></div>
      <p>Contract bytecode confirmed on Robinhood Chain (4663) at block ${escape(Number(d.block).toLocaleString())}. Bytecode is not an audit. Check the address against <a href="${escape(source)}" target="_blank" rel="noopener noreferrer">${sourceLabel}</a> before you trade, and never sign anything a DM sends you.</p>
      <p class="links"><a href="https://robinhoodchain.blockscout.com/address/${escape(ca)}" target="_blank" rel="noopener noreferrer">Blockscout ${arrow}</a>${info.launchpad && /^https:\/\//.test(info.launchpad) ? `<a href="${escape(info.launchpad)}" target="_blank" rel="noopener noreferrer">Launchpad ${arrow}</a>` : ''}</p>
      <section class="burn-panel" id="burnPanel" aria-label="SNTL burn snapshot" aria-live="polite"><p class="hint">Loading burn snapshot…</p></section>
      <section class="burn-panel" id="copiesPanel" aria-label="Copies of the SNTL ticker" aria-live="polite"><p class="hint">Checking for ticker copies…</p></section>`;
    void loadBurn(ca);
    void loadCopies(ca);
    el('copyCa').addEventListener('click', async () => {
      const b = el<HTMLButtonElement>('copyCa');
      try { await navigator.clipboard.writeText(ca); b.textContent = 'Copied'; } catch { getSelection()?.selectAllChildren(el('tokenCa')); b.textContent = 'Press Ctrl+C'; }
      setTimeout(() => (b.textContent = 'Copy'), 1600);
    });
  } catch {
    body.innerHTML = '<p class="notice-big">Not live yet.</p><p class="error">The configured address has no contract on Robinhood Chain right now, so it is not shown. Trust only announcements from @sentinelhood.</p>';
  }
}

async function loadBurn(ca: string) {
  const panel = el('burnPanel');
  try {
    const response = await fetch('/burn.json', { cache: 'no-store', signal: AbortSignal.timeout(10000) });
    if (!response.ok) throw new Error('Snapshot unavailable');
    const s = validateBurn(await response.json(), ca);
    const pct = burnPercent(s);
    const when = new Date(s.timestamp).toLocaleString('en-GB', { timeZone: 'UTC', day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
    panel.innerHTML = `<div class="burn-head"><span class="tag gold">BURNED</span><span class="badge wait">Snapshot</span></div>
      <p class="burn-total" title="${escape(tokenAmount(s.burnedRaw))} SNTL">${escape(tokenAmount(s.burnedRaw, 2))}<span>SNTL</span></p>
      <div class="burn-bar" role="img" aria-label="${escape(pct)}% of minted supply burned"><i style="--w:${Math.min(100, Number(pct) || 0)}%"></i></div>
      <p class="burn-facts"><span><b>${escape(pct)}%</b> of supply</span><span><b>${escape(s.burnEventCount)}</b> burns</span></p>
      <details><summary>Exact supply figures</summary><dl class="kv">
        ${row('Minted', escape(tokenAmount(s.mintedRaw)))}${row('Burned', escape(tokenAmount(s.burnedRaw)))}${row('Remaining', escape(tokenAmount(s.remainingRaw)))}
      </dl><p class="hint">Zero-address transfers only. Minted minus burned matches totalSupply at this block.</p></details>
      <p class="burn-meta">Updated ${escape(when)} UTC · Block <a href="https://robinhoodchain.blockscout.com/block/${s.block}" target="_blank" rel="noopener noreferrer">${escape(s.block.toLocaleString('en-US'))}</a></p>
      <p class="links">${s.latestBurns.length ? `<a href="https://robinhoodchain.blockscout.com/tx/${escape(s.latestBurns[0].tx)}" target="_blank" rel="noopener noreferrer">Latest burn ${arrow}</a>` : ''}<a href="/burn.json" target="_blank" rel="noopener noreferrer">Raw snapshot JSON ${arrow}</a></p>`;
  } catch {
    panel.textContent = 'Burn snapshot unavailable. No burn total is shown until the snapshot passes validation.';
  }
}

// Pons tokens that reuse the $SNTL ticker or name in the last 24h (public/copies.json, from the pons-launch-watch skill).
async function loadCopies(ca: string) {
  const panel = el('copiesPanel');
  try {
    const response = await fetch('/copies.json', { cache: 'no-store', signal: AbortSignal.timeout(10000) });
    if (!response.ok) throw new Error('unavailable');
    const s = validateCopies(await response.json(), ca);
    const when = ago(s.generatedAt) || 'recently';
    const list = s.copies.map((c) => `<li><code>${escape(c.symbol || '?')}</code> <small>${escape(c.name || '')}</small>
        <a href="/?ca=${escape(c.token)}">${escape(short(c.token))}</a></li>`).join('');
    panel.innerHTML = `<div class="burn-head"><span class="tag gold">COPIES OF THIS TICKER</span><span class="badge ${s.copyCount ? 'wait' : 'ok'}">${s.copyCount ? `${s.copyCount} found` : 'None'}</span></div>
      <p class="burn-facts"><span><b>${escape(s.copyCount)}</b> Pons tokens named SNTL or Sentinel</span><span>out of <b>${escape(Number(s.launches).toLocaleString())}</b> launches in ${escape(s.windowHours)}h</span></p>
      ${s.copyCount ? `<ul class="copy-list">${list}</ul><p class="hint">Only the address above is $SNTL. These share the name, which is not proof of a scam. Check the CA before you buy.</p>` : '<p class="hint">Nobody has launched a token with this ticker or name on Pons in the window. Only the address above is $SNTL.</p>'}
      <p class="burn-meta">Checked ${escape(when)} · Block ${escape(s.block.toLocaleString('en-US'))} · <a href="/skills/pons-launch-watch.md" target="_blank" rel="noopener">pons-launch-watch skill ${arrow}</a></p>`;
  } catch {
    panel.textContent = 'Ticker-copy check unavailable right now.';
  }
}

// ---------- Sentinel Guard (public/guards.json from scripts/snapshot-guards.py) ----------
let guardsCache: Promise<ReturnType<typeof validateGuards>> | null = null;
const loadGuardsJson = () => (guardsCache ??= fetch('/guards.json', { cache: 'no-store', signal: AbortSignal.timeout(10000) })
  .then((r) => { if (!r.ok) throw new Error('unavailable'); return r.json(); }).then(validateGuards)
  .catch((e) => { guardsCache = null; throw e; }));
const day = (iso: string) => new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });

async function loadGuards() {
  const list = el('guardList'), meta = el('guardMeta');
  try {
    const s = await loadGuardsJson();
    const active = s.guards.filter((g) => g.active);
    list.innerHTML = active.map((g) => `<li><code>${escape(g.symbol || '?')}</code> <small>${escape(g.name || '')}</small>
      <a href="/?ca=${escape(g.token)}">${escape(short(g.token))}</a>
      <span class="badge ${g.copyCount ? 'wait' : 'ok'}">${g.copyCount ? `${g.copyCount} cop${g.copyCount > 1 ? 'ies' : 'y'} in ${s.windowHours}h` : 'No copies'}</span>
      <small>until ${escape(day(g.expiresAt))}</small></li>`).join('') || '<li class="hint">No guarded tokens yet. Be the first.</li>';
    meta.textContent = `${active.length} active guard${active.length === 1 ? '' : 's'} · updated ${ago(s.generatedAt) || 'recently'} · block ${s.block.toLocaleString('en-US')}`;
  } catch {
    list.innerHTML = '<li class="hint">Guard list unavailable right now.</li>';
  }
}

async function guardStatus(token: string) {
  const cell = el('guardStatus');
  try {
    const s = await loadGuardsJson();
    const g = s.guards.find((x) => x.token.toLowerCase() === token.toLowerCase());
    if (!cell.isConnected) return;
    if (!g) { cell.innerHTML = '<span class="hint">Not guarded</span> <a href="#guard">How</a>'; return; }
    const copies = g.copies.map((c) => `<a href="/?ca=${escape(c.token)}">${escape(c.symbol || short(c.token))}</a>`).join(', ');
    cell.innerHTML = g.active
      ? `<span class="badge ok">Guarded until ${escape(day(g.expiresAt))}</span> <small>${escape(tokenAmount(g.burnedRaw, 0))} SNTL burned by the deployer · <a href="https://robinhoodchain.blockscout.com/tx/${escape(g.lastTx)}" target="_blank" rel="noopener noreferrer">burn tx</a></small>${g.copyCount ? `<br><small>${escape(g.copyCount)} cop${g.copyCount > 1 ? 'ies' : 'y'} in ${escape(s.windowHours)}h: ${copies}</small>` : '<br><small>No copies in the last 24h</small>'}`
      : `<span class="badge">Expired ${escape(day(g.expiresAt))}</span>`;
  } catch {
    if (cell.isConnected) cell.innerHTML = '<span class="hint">Unavailable right now</span>';
  }
}

el('guardForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const out = el('guardHow');
  const token = value('guardToken');
  let data: string;
  try { data = guardCalldata(token, 1_000_000n); } catch { show(out, '<p class="error">Enter a Pons token address (0x + 40 hex). It cannot be the SNTL address.</p>'); return; }
  show(out, '<p class="hint">Reading the Pons factory record…</p>');
  try {
    const d = await api('token', token);
    if (value('guardToken') !== token) return;
    if (!d.pons) { show(out, '<p class="error">This address has no Pons v2 launch record, so a burn for it would not count. Nothing to send.</p>'); return; }
    show(out, `<p>Send this from the deployer <a href="https://robinhoodchain.blockscout.com/address/${escape(d.pons.deployer)}" target="_blank" rel="noopener noreferrer"><code>${escape(short(d.pons.deployer))}</code></a> of <b>${escape(d.symbol || 'this token')}</b>. From any other wallet the burn is lost and does not count.</p>
      <dl class="kv">${row('To', '<code>SNTL 0x2da80b9D…CbD0</code>')}${row('Value', '0 ETH')}${row('Burns', '1,000,000 SNTL')}</dl>
      <div class="cmd"><code id="guardData">${escape(data)}</code><button class="btn small" id="copyGuardData" type="button">Copy data</button></div>
      <p class="hint">Paste it as the hex data of a transaction to the SNTL contract (wallets call this "custom data" or "hex data"). It calls the token's own public <code>burn</code>, with your token address added at the end. No approval, no other contract. The guard shows up here within about 30 minutes.</p>`);
    el('copyGuardData').addEventListener('click', () => copyText(el<HTMLButtonElement>('copyGuardData'), data, el('guardData')));
  } catch (err) {
    show(out, `<p class="error">Factory read unavailable: ${escape((err as Error).message)}</p>`);
  }
});

// Live PR status from GitHub via the API (edge-cached). Falls back to the saved list on any error.
async function loadContributions() {
  const meta = el('contribMeta');
  try {
    const d = await api('contributions');
    const saved = new Map(CONTRIBUTIONS.map((c) => [c.pr, c.what]));
    const prs: Contribution[] = (Array.isArray(d.prs) ? d.prs : [])
      .filter((p: Contribution) => Number.isSafeInteger(p?.pr) && typeof p.title === 'string' && ['merged', 'open', 'closed'].includes(p.state))
      .map((p: Contribution) => ({ ...p, review: p.state === 'open' && ['approved', 'changes_requested', 'review'].includes(p.review as string) ? p.review : undefined, what: saved.get(p.pr) }));
    if (!prs.length) throw new Error('empty');
    el('contribList').innerHTML = contributionRows(prs);
    meta.textContent = `Live from GitHub · checked ${new Date(d.checkedAt).toLocaleString()}. Only merged PRs are part of Aeon.`;
  } catch {
    meta.textContent = 'GitHub is unreachable right now, so saved statuses are shown. Open each PR to confirm.';
  }
}

// ---------- live Pons v2 launches ----------
type Launch = { token: string; deployer: string; block: number; tx: string; name: string | null; symbol: string | null; launchedAt: string | null; creatorTaxBps: number | null; phase: number | null; nativePair: boolean | null };
const PHASE_SHORT = ['Curve', 'Swept', 'v4 pool', 'Rescued'];
function ago(iso: string | null) {
  const s = iso ? Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000)) : NaN;
  if (!Number.isFinite(s)) return '';
  return s < 60 ? `${s}s ago` : s < 3600 ? `${Math.floor(s / 60)}m ago` : s < 86400 ? `${Math.floor(s / 3600)}h ago` : `${Math.floor(s / 86400)}d ago`;
}
async function loadLaunches() {
  const list = el('launchList'), meta = el('launchMeta'), button = el<HTMLButtonElement>('launchRefresh');
  button.disabled = true;
  try {
    const d = await api('launches');
    const rows: Launch[] = (Array.isArray(d.launches) ? d.launches : []).filter((l: Launch) => ADDRESS.test(l?.token) && ADDRESS.test(l?.deployer) && TX_HASH.test(l?.tx));
    // Tickers are not unique on Pons. Flag repeats so nobody buys the wrong one by name.
    const seen = new Map<string, number>();
    for (const l of rows) if (l.symbol) seen.set(l.symbol.toUpperCase(), (seen.get(l.symbol.toUpperCase()) || 0) + 1);
    list.innerHTML = rows.map((l, i) => {
      const dup = l.symbol && (seen.get(l.symbol.toUpperCase()) || 0) > 1;
      const tax = Number.isSafeInteger(l.creatorTaxBps) ? bps(l.creatorTaxBps) : '—';
      return `<li style="--d:${i}">
        <div class="who"><strong>${escape(l.symbol || '?')}</strong>${dup ? '<span class="badge wait">Same ticker</span>' : ''}<small>${escape(l.name || 'Unnamed')}</small></div>
        <span class="facts"><span>tax <b>${escape(tax)}</b></span><span>${escape(PHASE_SHORT[l.phase as number] || '?')}</span><span>${l.nativePair === false ? 'token pair' : 'ETH'}</span></span>
        <span class="meta"><a href="https://robinhoodchain.blockscout.com/tx/${escape(l.tx)}" target="_blank" rel="noopener noreferrer">${escape(ago(l.launchedAt) || `#${l.block}`)}</a><code title="${escape(l.token)}">${escape(short(l.token))}</code></span>
        <button class="btn small" data-check-ca="${escape(l.token)}">Check</button>
      </li>`;
    }).join('') || '<li class="empty">No launches in the scanned window.</li>';
    meta.textContent = `${rows.length} newest launches · factory read at block ${Number(d.block).toLocaleString()}. ${d.warning}`;
  } catch (e) {
    list.innerHTML = `<li class="error">Factory read unavailable: ${escape((e as Error).message)}</li>`;
  } finally {
    button.disabled = false;
  }
}
el('launchList').addEventListener('click', (e) => {
  const ca = (e.target as HTMLElement).closest<HTMLElement>('[data-check-ca]')?.dataset.checkCa;
  if (ca && ADDRESS.test(ca)) inspectAddress(ca);
});
el('launchRefresh').addEventListener('click', () => void loadLaunches());

// ---------- shipping log (this repo's commits) ----------
type Ship = { sha: string; url: string; title: string; type: string; date: string };
const SHIP_TYPE: Record<string, string> = { feat: 'Feature', fix: 'Fix', ui: 'Design', site: 'Site', token: 'Token', docs: 'Docs', skill: 'Skill' };
async function loadShiplog() {
  const list = el('shipList'), meta = el('shipMeta');
  try {
    const d = await api('shiplog');
    const rows: Ship[] = (Array.isArray(d.commits) ? d.commits : []).filter((c: Ship) => /^[0-9a-f]{7}$/.test(c?.sha) && typeof c.title === 'string' && /^https:\/\/github\.com\/sentinelhood\/robinhood-sentinel\/commit\/[0-9a-f]{40}$/.test(c.url));
    if (!rows.length) throw new Error('empty');
    list.innerHTML = rows.map((c, i) => `<li style="--d:${i}">
      <time datetime="${escape(c.date)}">${escape(new Date(c.date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }))}</time>
      <span class="badge">${escape(SHIP_TYPE[c.type] || 'Update')}</span>
      <a href="${escape(c.url)}" target="_blank" rel="noopener noreferrer">${escape(c.title)}</a>
      <code>${escape(c.sha)}</code>
    </li>`).join('');
    meta.textContent = `${d.dataRefreshes ? `Plus ${d.dataRefreshes} automated burn snapshot refresh${d.dataRefreshes > 1 ? 'es' : ''} in the same window${d.lastDataRefresh ? `, last ${ago(d.lastDataRefresh)}` : ''}. ` : ''}Checked ${ago(d.checkedAt) || 'just now'}.`;
  } catch {
    list.innerHTML = '<li class="hint">GitHub is unreachable right now. The full history is on <a href="https://github.com/sentinelhood/robinhood-sentinel/commits/main" target="_blank" rel="noopener noreferrer">GitHub</a>.</li>';
  }
}

renderWatch();
void loadHookUsage();
void loadToken();
void loadContributions();
void loadLaunches();
void loadGuards();
void loadShiplog();
// Share links: sentinelhood.com/?ca=0x... opens the Inspector on that address.
const sharedCa = new URLSearchParams(location.search).get('ca');
if (sharedCa && ADDRESS.test(sharedCa)) inspectAddress(sharedCa);
// Place the indicator in its final spot before first paint (no slide-in).
spy(true);
void network();

// Which position to land on:
//  - refresh / back-forward in this tab: exactly where the reader was;
//  - opened with #section: that section, 16px under the header;
//  - otherwise: the top.
const navType = (performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined)?.type;
let saved: Saved | null = null;
try { saved = JSON.parse(sessionStorage.getItem(SCROLL_KEY) || 'null'); } catch { saved = null; }
if ((navType === 'reload' || navType === 'back_forward') && saved && saved.path === location.pathname && (saved.anchor === 'top' || ANCHORS.includes(saved.anchor))) {
  settleOn(saved);
} else if (location.hash && /^#[\w-]+$/.test(location.hash) && document.querySelector(location.hash)) {
  settleOn({ anchor: location.hash, offset: -16 });
}
// Keep the network card fresh while the tab is visible (one cheap read every 20s).
setInterval(() => document.visibilityState === 'visible' && void network(), 20000);
// New launches every minute while the tab is visible (the API edge cache makes this one shared read).
setInterval(() => document.visibilityState === 'visible' && void loadLaunches(), 60000);
