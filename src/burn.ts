export const SNTL = '0x2da80b9d1bc1b323693c80c76eb4a321ec08cbd0';
type BurnSnapshot = {
  chainId: number; token: string; decimals: number; fromBlock: number; block: number;
  blockHash: string; timestamp: string; mintedRaw: string; burnedRaw: string; remainingRaw: string;
  mintEventCount: number; burnEventCount: number;
  latestBurns: { tx: string; block: number; logIndex: number; amountRaw: string }[];
};
const raw = (x: unknown): x is string => typeof x === 'string' && /^(0|[1-9]\d{0,77})$/.test(x);
const hash = (x: unknown) => typeof x === 'string' && /^0x[\da-f]{64}$/i.test(x);
const integer = (x: unknown): x is number => Number.isSafeInteger(x) && Number(x) >= 0;
const address = (x: unknown): x is string => typeof x === 'string' && /^0x[\da-f]{40}$/i.test(x);
const text = (x: unknown) => x === null || (typeof x === 'string' && x.length <= 64);

type CopiesSnapshot = {
  chainId: number; official: string; block: number; generatedAt: string; windowHours: number;
  launches: number; copyCount: number;
  copies: { token: string; deployer: string; block: number; symbol: string | null; name: string | null }[];
};
// public/copies.json must name the same official token, and no listed copy may be the official address.
export function validateCopies(value: unknown, ca: string): CopiesSnapshot {
  const s = value as CopiesSnapshot;
  if (!s || ca.toLowerCase() !== SNTL || typeof s.official !== 'string' || s.official.toLowerCase() !== SNTL ||
      s.chainId !== 4663 || !integer(s.block) || !integer(s.launches) || !integer(s.copyCount) || !integer(s.windowHours) ||
      typeof s.generatedAt !== 'string' || !Number.isFinite(Date.parse(s.generatedAt)) ||
      !Array.isArray(s.copies) || s.copies.length > 20 || s.copies.length > s.copyCount || s.copyCount > s.launches ||
      (s.copyCount > 0 && s.copies.length === 0)) throw new Error('Invalid copies snapshot');
  for (const c of s.copies) {
    if (!c || !address(c.token) || !address(c.deployer) || !integer(c.block) || c.block > s.block ||
        !text(c.symbol) || !text(c.name) || c.token.toLowerCase() === SNTL) throw new Error('Invalid copy entry');
  }
  return s;
}

type Guard = {
  token: string; deployer: string; symbol: string | null; name: string | null; burnedRaw: string; burns: number;
  since: string; expiresAt: string; active: boolean; lastTx: string; copyCount: number;
  copies: { token: string; deployer: string; block: number; symbol: string | null; name: string | null }[];
};
type GuardsSnapshot = {
  chainId: number; token: string; block: number; generatedAt: string; minBurnRaw: string; periodDays: number;
  windowHours: number; launches: number; guards: Guard[];
};
const date = (x: unknown) => typeof x === 'string' && Number.isFinite(Date.parse(x));
// public/guards.json: SNTL burns that guard a Pons token. Every field is checked before anything is shown.
export function validateGuards(value: unknown): GuardsSnapshot {
  const s = value as GuardsSnapshot;
  if (!s || s.chainId !== 4663 || typeof s.token !== 'string' || s.token.toLowerCase() !== SNTL || !integer(s.block) ||
      !date(s.generatedAt) || !raw(s.minBurnRaw) || BigInt(s.minBurnRaw) === 0n || !integer(s.periodDays) || s.periodDays < 1 ||
      !integer(s.windowHours) || !integer(s.launches) || !Array.isArray(s.guards) || s.guards.length > 500) throw new Error('Invalid guards snapshot');
  for (const g of s.guards) {
    if (!g || !address(g.token) || !address(g.deployer) || g.token.toLowerCase() === SNTL || !text(g.symbol) || !text(g.name) ||
        !raw(g.burnedRaw) || BigInt(g.burnedRaw) < BigInt(s.minBurnRaw) || !integer(g.burns) || g.burns < 1 ||
        !date(g.since) || !date(g.expiresAt) || Date.parse(g.expiresAt) <= Date.parse(g.since) || typeof g.active !== 'boolean' ||
        !hash(g.lastTx) || !integer(g.copyCount) || !Array.isArray(g.copies) || g.copies.length > Math.min(5, g.copyCount) ||
        (g.copyCount > 0 && g.copies.length === 0)) throw new Error('Invalid guard entry');
    for (const c of g.copies) {
      if (!c || !address(c.token) || !address(c.deployer) || !integer(c.block) || c.block > s.block || !text(c.symbol) || !text(c.name) ||
          c.token.toLowerCase() === g.token.toLowerCase()) throw new Error('Invalid guard copy');
    }
  }
  return s;
}

// Calldata for burn(amount) on SNTL with the guarded token appended as one extra 32-byte word.
export function guardCalldata(token: string, wholeSntl: bigint): string {
  if (!address(token) || token.toLowerCase() === SNTL || wholeSntl <= 0n) throw new Error('Invalid guard input');
  const word = (x: string) => x.padStart(64, '0');
  return '0x42966c68' + word((wholeSntl * 10n ** 18n).toString(16)) + word(token.slice(2).toLowerCase());
}

export function validateBurn(value: unknown, ca: string): BurnSnapshot {
  const s = value as BurnSnapshot;
  if (!s || ca.toLowerCase() !== SNTL || typeof s.token !== 'string' || s.token.toLowerCase() !== SNTL ||
      s.chainId !== 4663 || s.decimals !== 18 || s.fromBlock !== 93500000 || !integer(s.block) || s.block < s.fromBlock ||
      !hash(s.blockHash) || typeof s.timestamp !== 'string' || !Number.isFinite(Date.parse(s.timestamp)) ||
      !raw(s.mintedRaw) || !raw(s.burnedRaw) || !raw(s.remainingRaw) ||
      !integer(s.mintEventCount) || s.mintEventCount < 1 || !integer(s.burnEventCount) ||
      !Array.isArray(s.latestBurns) || s.latestBurns.length !== Math.min(5, s.burnEventCount)) throw new Error('Invalid burn snapshot');
  if (BigInt(s.mintedRaw) <= 0n || BigInt(s.mintedRaw) - BigInt(s.burnedRaw) !== BigInt(s.remainingRaw) ||
      (s.burnEventCount === 0 && BigInt(s.burnedRaw) !== 0n)) throw new Error('Supply mismatch');
  for (const event of s.latestBurns) {
    if (!event || !hash(event.tx) || !integer(event.block) || event.block < s.fromBlock || event.block > s.block ||
        !integer(event.logIndex) || !raw(event.amountRaw) || BigInt(event.amountRaw) > BigInt(s.burnedRaw)) throw new Error('Invalid burn event');
  }
  return s;
}

// String/BigInt only: even the fractional portion never passes through Number.
export function tokenAmount(raw: string, places = 18): string {
  const n = BigInt(raw);
  const whole = (n / 10n ** 18n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  const fraction = (n % 10n ** 18n).toString().padStart(18, '0').slice(0, places).replace(/0+$/, '');
  return whole + (fraction ? `.${fraction}` : '');
}

export function burnPercent(s: BurnSnapshot): string {
  const scaled = BigInt(s.burnedRaw) * 1000000n / BigInt(s.mintedRaw);
  return `${scaled / 10000n}.${(scaled % 10000n).toString().padStart(4, '0')}`;
}