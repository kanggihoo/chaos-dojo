// Problem workload: one order per iteration. The harness wrapper owns timing, cohorts and logging.
// `n` is the iteration index within the cohort, so product and quantity depend only on (seed, n).
function mix(x) {
  x = Math.imul(x ^ (x >>> 16), 0x45d9f3b);
  x = Math.imul(x ^ (x >>> 16), 0x45d9f3b);
  return (x ^ (x >>> 16)) >>> 0;
}

export function request({ baseUrl, seed, n }) {
  const h = mix(seed * 1000003 + n);
  const productId = 'p-' + String((h % 20) + 1).padStart(3, '0');
  const quantity = ((h >>> 8) % 10) + 1;
  return {
    method: 'POST',
    url: `${baseUrl}/orders`,
    body: { productId, quantity },
  };
}
