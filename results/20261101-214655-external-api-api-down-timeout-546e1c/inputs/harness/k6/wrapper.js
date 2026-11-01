// Harness k6 wrapper, shared by every problem. Options come from a harness-generated JSON file;
// every request is logged as one JSON line so the harness keeps per-request raw results.
import http from 'k6/http';
import exec from 'k6/execution';
import { request } from '/problem/script.js';

const cfg = JSON.parse(open(`/out/${__ENV.CHAOS_PHASE}.json`));
export const options = cfg.options;

function send(cohort, n, timeoutS) {
  const id = crypto.randomUUID();
  const r = request({ baseUrl: cfg.baseUrl, seed: cfg.seed, n });
  const params = {
    headers: { 'Content-Type': 'application/json', 'X-Request-Id': id, 'X-Chaos-Cohort': cohort },
    tags: { cohort },
    timeout: `${timeoutS}s`,
    responseCallback: http.expectedStatuses(201),
  };
  const body = JSON.stringify(r.body);
  const issued = Date.now();
  console.log(JSON.stringify({ k: 'issue', id, cohort, n, issued, req: r.body }));
  return { id, cohort, n, issued, call: () => http.asyncRequest(r.method, r.url, body, params) };
}

function done(s, res) {
  const rec = { k: 'done', id: s.id, cohort: s.cohort, done: Date.now(), status: res.status, error_code: res.error_code || 0 };
  if (res.status === 201) {
    try { rec.res = res.json(); } catch (e) { rec.res = null; }
  } else if (res.status > 0) {
    try { rec.type = res.json('type'); } catch (e) { rec.type = null; }
  }
  console.log(JSON.stringify(rec));
  return rec;
}

export async function warmup() {
  const s = send('warmup', exec.scenario.iterationInTest, cfg.timeoutS);
  done(s, await s.call());
}

export async function measured() {
  if (exec.scenario.iterationInTest === 0) {
    console.log(JSON.stringify({ k: 't0', t: exec.scenario.startTime }));
  }
  const s = send('measured', exec.scenario.iterationInTest, cfg.timeoutS);
  done(s, await s.call());
}

// One VU issues a probe every interval on a grid from the scenario start (= planned removal time),
// and stops issuing after `consecutive` in-budget 201s in issue order, counting only probes issued
// after the tolerance (so they are after any valid actual removal).
export async function probe() {
  const p = cfg.probe;
  const start = exec.scenario.startTime;
  const results = [];
  const pending = [];
  let stop = false;
  const check = () => {
    let run = 0;
    for (const r of results) {
      if (r === undefined) return;
      run = r ? run + 1 : 0;
      if (run >= p.consecutive) { stop = true; return; }
    }
  };
  for (let k = 0; k < p.count && !stop; k++) {
    const wait = start + k * p.intervalMs - Date.now();
    if (wait > 0) await new Promise((res) => setTimeout(res, wait));
    if (stop) break;
    const s = send('probe', k, cfg.timeoutS);
    const counted = s.issued >= start + p.toleranceMs;
    const idx = counted ? results.push(undefined) - 1 : -1;
    pending.push(s.call().then((res) => {
      const rec = done(s, res);
      if (idx >= 0) {
        results[idx] = rec.status === 201 && rec.done - s.issued <= p.budgetMs;
        check();
      }
    }));
  }
  await Promise.all(pending);
}
