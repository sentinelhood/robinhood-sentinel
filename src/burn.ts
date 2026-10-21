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