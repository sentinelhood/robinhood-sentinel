// public/graduations.json from scripts/snapshot-graduations.py (the pons-graduation-watch skill).
// Every field is checked before anything is shown. Amounts stay strings and are formatted with BigInt.
export type Graduated = {
  token: string; symbol: string | null; name: string | null; deployer: string | null; block: number; tx: string;
  quoteRaw: string; pairSymbol: string | null; pairDecimals: number | null; phase: number | null;
};
export type GraduationsSnapshot = {
  chainId: number; block: number; windowHours: number; generatedAt: string; launches: number; graduations: number; graduated: Graduated[];
};

const integer = (x: unknown): x is number => Number.isSafeInteger(x) && Number(x) >= 0;
const address = (x: unknown): x is string => typeof x === 'string' && /^0x[\da-f]{40}$/.test(x);
const hash = (x: unknown): x is string => typeof x === 'string' && /^0x[\da-f]{64}$/.test(x);
const text = (x: unknown) => x === null || (typeof x === 'string' && x.length > 0 && x.length <= 64);
const unsigned = (x: unknown): x is string => typeof x === 'string' && /^(0|[1-9]\d{0,77})$/.test(x);

export function validateGraduations(value: unknown): GraduationsSnapshot {
  const s = value as GraduationsSnapshot;
  if (!s || s.chainId !== 4663 || !integer(s.block) || typeof s.windowHours !== 'number' || !(s.windowHours > 0 && s.windowHours <= 72) ||
      typeof s.generatedAt !== 'string' || !Number.isFinite(Date.parse(s.generatedAt)) || !integer(s.launches) || !integer(s.graduations) ||
      !Array.isArray(s.graduated) || s.graduated.length > 20 || s.graduated.length > s.graduations ||
      (s.graduations > 0 && s.graduated.length === 0)) {
    throw new Error('Invalid graduations snapshot');
  }
  const seen = new Set<string>();
  let previous = Infinity;
  for (const g of s.graduated) {
    if (!g || !address(g.token) || seen.has(g.token) || !text(g.symbol) || !text(g.name) || !(g.deployer === null || address(g.deployer)) ||
        !integer(g.block) || g.block > s.block || g.block > previous || !hash(g.tx) || !unsigned(g.quoteRaw) ||
        !text(g.pairSymbol) || !(g.pairDecimals === null || (integer(g.pairDecimals) && g.pairDecimals <= 36)) ||
        !(g.phase === null || (integer(g.phase) && g.phase <= 3))) {
      throw new Error('Invalid graduation entry');
    }
    seen.add(g.token);
    previous = g.block;   // newest first
  }
  return s;
}
