// public/movers.json from scripts/snapshot-movers.py (the pons-curve-movers skill).
// Every field is checked before anything is shown. Amounts stay strings and are formatted with BigInt.
export type Mover = {
  token: string; symbol: string | null; name: string | null; buys: number; sells: number; traders: number;
  // Busiest recipient: a share is published only for a wallet. A contract is usually a router used by many people.
  topTraderTrades: number; topRecipientKind: 'wallet' | 'contract' | null; topTraderShare: number | null;
  volumeRaw: string; netRaw: string; pairSymbol: string | null; pairDecimals: number | null; phase: number; progress: number | null;
};
export type MoversSnapshot = {
  chainId: number; block: number; windowHours: number; generatedAt: string; trades: number; curves: number; skipped: number; movers: Mover[];
};

const integer = (x: unknown): x is number => Number.isSafeInteger(x) && Number(x) >= 0;
const address = (x: unknown): x is string => typeof x === 'string' && /^0x[\da-f]{40}$/.test(x);
const text = (x: unknown) => x === null || (typeof x === 'string' && x.length > 0 && x.length <= 64);
const unsigned = (x: unknown): x is string => typeof x === 'string' && /^(0|[1-9]\d{0,77})$/.test(x);
const signed = (x: unknown): x is string => typeof x === 'string' && /^-?(0|[1-9]\d{0,77})$/.test(x) && x !== '-0';

export function validateMovers(value: unknown): MoversSnapshot {
  const s = value as MoversSnapshot;
  if (!s || s.chainId !== 4663 || !integer(s.block) || typeof s.windowHours !== 'number' || !(s.windowHours > 0 && s.windowHours <= 24) ||
      typeof s.generatedAt !== 'string' || !Number.isFinite(Date.parse(s.generatedAt)) || !integer(s.trades) || !integer(s.curves) ||
      !integer(s.skipped) || s.curves > s.trades || !Array.isArray(s.movers) || s.movers.length > 25 || s.movers.length > s.curves) {
    throw new Error('Invalid movers snapshot');
  }
  const seen = new Set<string>();
  let previous = [Infinity, Infinity];
  for (const m of s.movers) {
    const trades = m && integer(m.buys) && integer(m.sells) ? m.buys + m.sells : -1;
    // Ranked by distinct traders, then trades (pons-curve-movers rank()).
    const outOfOrder = m && (m.traders > previous[0] || (m.traders === previous[0] && trades > previous[1]));
    if (!m || !address(m.token) || seen.has(m.token) || !text(m.symbol) || !text(m.name) || trades < 1 || outOfOrder ||
        !integer(m.traders) || m.traders < 1 || m.traders > trades || !unsigned(m.volumeRaw) || !signed(m.netRaw) ||
        // Busiest wallet: at least an even share, at most every trade, and its % must match the counts.
        !integer(m.topTraderTrades) || m.topTraderTrades < 1 || m.topTraderTrades > trades ||
        m.topTraderTrades * m.traders < trades || (m.traders === 1 && m.topTraderTrades !== trades) ||
        !(m.topRecipientKind === 'wallet' || m.topRecipientKind === 'contract' || m.topRecipientKind === null) ||
        (m.topRecipientKind === 'wallet'
          ? typeof m.topTraderShare !== 'number' || Math.abs(m.topTraderShare - Math.round(1000 * m.topTraderTrades / trades) / 10) > 0.05
          : m.topTraderShare !== null) ||
        !text(m.pairSymbol) || !(m.pairDecimals === null || (integer(m.pairDecimals) && m.pairDecimals <= 36)) ||
        !integer(m.phase) || m.phase > 3 ||
        !(m.progress === null || (typeof m.progress === 'number' && m.progress >= 0 && m.progress <= 100)) ||
        (m.phase !== 0 && m.progress !== null)) {
      throw new Error('Invalid mover entry');
    }
    seen.add(m.token);
    previous = [m.traders, trades];
  }
  return s;
}

// What the movers list shows: '?' without decimals, '<0.0001' for non-zero amounts too small for 4 places, never '-0'.
// Must match amount() in skills/pons-curve-movers/pons_curve_movers.py.
export function displayAmount(raw: string, decimals: number | null, signed = false): string {
  if (decimals === null) return '?';
  const negative = raw.startsWith('-');
  const abs = negative ? raw.slice(1) : raw;
  let s = quoteAmount(abs, decimals);
  if (s === '0' && BigInt(abs) !== 0n) s = '<0.0001';
  return signed ? (negative ? '-' : '+') + s : (negative ? '-' : '') + s;
}

// Integer string with `decimals` places -> "1,234.5678" (at most `places` decimals, trailing zeros dropped).
export function quoteAmount(raw: string, decimals: number, places = 4): string {
  const negative = raw.startsWith('-');
  const n = BigInt(negative ? raw.slice(1) : raw);
  const unit = 10n ** BigInt(decimals);
  const whole = (n / unit).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  const fraction = decimals ? (n % unit).toString().padStart(decimals, '0').slice(0, places).replace(/0+$/, '') : '';
  return (negative ? '-' : '') + whole + (fraction ? `.${fraction}` : '');
}
