import './app.css';

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

const mark = `<svg class="mark" viewBox="0 0 40 40" aria-hidden="true"><path d="M20 3 37 20 20 37 3 20Z" fill="none" stroke="currentColor" stroke-width="2.6"/><path d="M20 11 29 20 20 29 11 20Z" fill="none" stroke="#f5f1e9" stroke-width="1.2"/><path d="M20 16.5 23.5 20 20 23.5 16.5 20Z" fill="currentColor"/></svg>`;
const arrow = `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 12 12 4M6 4h6v6" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>`;

document.querySelector<HTMLDivElement>('#root')!.innerHTML = `
<header class="top">
  <a class="brand" href="#" aria-label="Sentinel home">${mark}<span><strong>SENTINEL</strong><small>ROBINHOOD CHAIN · 4663</small></span></a>
  <nav aria-label="Sections" id="nav">
    <a href="#inspect" data-section>Inspect</a><a href="#watch" data-section>Watchlist</a><a href="#aeon" data-section>Aeon</a>
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

      <article class="card notice reveal" style="--d:3" aria-labelledby="tokenTitle">
        <span class="tag gold" id="tokenTitle">OFFICIAL TOKEN</span>
        <p class="notice-big">Not live yet.</p>
        <p>Sentinel has no token today. Any contract address that claims to be Sentinel is not ours. Announcements come only from <a href="https://x.com/sentinelhood" target="_blank" rel="noopener noreferrer">@sentinelhood</a>.</p>
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

  <section class="card aeon reveal" id="aeon" aria-labelledby="aeonTitle">
    <div class="aeon-main">
      <span class="tag gold">03 · AEON</span>
      <h2 id="aeonTitle">The gap it fills.</h2>
      <p class="muted">Aeon's <code>onchain-monitor</code> covers Ethereum, Base, Arbitrum, Optimism and Polygon, but not Robinhood Chain. The Sentinel Pack adds that. It watches addresses for nonce, balance and bytecode changes, reads only from the official Robinhood Chain RPC, and needs no keys.</p>
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
  const card = el('inspect');
  const button = el('inspectForm').querySelector('button')!;
  button.disabled = true;
  busy(card, true);
  show(out, '<p class="hint">Reading chain…</p>');
  try {
    const data = await api(action, v);
    const link = `<a class="link-out" href="https://robinhoodchain.blockscout.com/${action === 'address' ? 'address' : 'tx'}/${v}" target="_blank" rel="noopener noreferrer">Open in Blockscout ${arrow}</a>`;
    if (action === 'address') {
      const kind = data.codeBytes ? 'Contract' : 'Account';
      show(out, `<h3><span class="badge">${kind}</span>${escape(short(v))}</h3><dl class="kv">${row('Balance', `${escape(eth(data.balanceWei))} ETH`)}${row('Bytecode', `${escape(Number(data.codeBytes).toLocaleString())} bytes`)}${row('Nonce', escape(data.nonce))}${row('Read at block', escape(Number(data.block).toLocaleString()))}</dl><p class="hint">${escape(data.warning)}</p>${link}`);
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
const ANCHORS = ['.hero', '#inspect', '#watch', '#aeon', '.foot'];
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

renderWatch();
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
