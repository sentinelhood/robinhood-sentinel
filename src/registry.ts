// public/registry.json from scripts/snapshot-registry.py (the hook-registry-check skill).
// Every field is checked before anything is shown.
export type RegistryStatus = 'code' | 'no-code' | 'no-rpc' | 'wrong-chain' | 'rpc-error';
export type RegistryChainEntry = { chain: string; address: string; status: RegistryStatus; flagsOk: boolean };
export type RegistryHook = { hook: string; stage: string | null; chains: RegistryChainEntry[]; builds: number; selectorsMatch: boolean };
export type RegistrySnapshot = {
  generatedAt: string;
  summary: { addresses: number; hooks: number; chains: number; withCode: number; noCode: number; unchecked: number; flagMismatch: number };
  chains: { chain: string; chainId: number; addresses: number; block: number | null; checked: boolean }[];
  hooks: RegistryHook[];
  problems: string[];
};

const STATUSES = new Set(['code', 'no-code', 'no-rpc', 'wrong-chain', 'rpc-error']);
const integer = (x: unknown): x is number => Number.isSafeInteger(x) && Number(x) >= 0;
const name = (x: unknown): x is string => typeof x === 'string' && /^[\w .()-]{1,48}$/.test(x);
const address = (x: unknown): x is string => typeof x === 'string' && /^0x[\da-f]{40}$/.test(x);

export function validateRegistry(value: unknown): RegistrySnapshot {
  const s = value as RegistrySnapshot;
  const t = s?.summary;
  if (!s || typeof s.generatedAt !== 'string' || !Number.isFinite(Date.parse(s.generatedAt)) || !t ||
      ![t.addresses, t.hooks, t.chains, t.withCode, t.noCode, t.unchecked, t.flagMismatch].every(integer) ||
      t.withCode + t.noCode + t.unchecked !== t.addresses || t.flagMismatch > t.addresses ||
      !Array.isArray(s.chains) || s.chains.length !== t.chains || !Array.isArray(s.hooks) || s.hooks.length !== t.hooks ||
      !Array.isArray(s.problems) || s.problems.length > 500 || !s.problems.every((p) => typeof p === 'string' && p.length <= 200)) {
    throw new Error('Invalid registry snapshot');
  }
  const chainNames = new Set<string>();
  let perChain = 0;
  for (const c of s.chains) {
    if (!c || !name(c.chain) || chainNames.has(c.chain) || !integer(c.chainId) || !integer(c.addresses) ||
        !(c.block === null || integer(c.block)) || c.checked !== (c.block !== null)) {
      throw new Error('Invalid registry chain');
    }
    chainNames.add(c.chain);
    perChain += c.addresses;
  }
  const seen = new Set<string>();
  let rows = 0, withCode = 0, noCode = 0, mismatch = 0;
  for (const h of s.hooks) {
    if (!h || !name(h.hook) || seen.has(h.hook) || !(h.stage === null || name(h.stage)) || !integer(h.builds) ||
        typeof h.selectorsMatch !== 'boolean' || !Array.isArray(h.chains) || h.chains.length < 1) {
      throw new Error('Invalid registry hook');
    }
    seen.add(h.hook);
    for (const e of h.chains) {
      if (!e || !chainNames.has(e.chain) || !address(e.address) || !STATUSES.has(e.status) || typeof e.flagsOk !== 'boolean') {
        throw new Error('Invalid registry entry');
      }
      rows += 1;
      withCode += Number(e.status === 'code');
      noCode += Number(e.status === 'no-code');
      mismatch += Number(!e.flagsOk);
    }
  }
  // The headline numbers must be what the rows say, so a hand-edited summary cannot show more than was read.
  if (rows !== t.addresses || perChain !== t.addresses || withCode !== t.withCode || noCode !== t.noCode || mismatch !== t.flagMismatch) {
    throw new Error('Registry summary does not match its rows');
  }
  return s;
}
