// catchme k6 shared library. Config comes from run.json written by plan.py (CATCHME_RUN).
import http from 'k6/http';
import { Counter } from 'k6/metrics';
import { randomSeed } from 'k6';

export const cfg = JSON.parse(open(__ENV.CATCHME_RUN));
const auth = cfg.auth || { mode: 'none' };

const tokens = cfg.tokens_file ? JSON.parse(open(cfg.tokens_file)) : [];
const ownMaps = cfg.exports_file ? JSON.parse(open(cfg.exports_file)) : {};

randomSeed((cfg.seed || 42) * 1000 + (__VU || 0));

// Statuses that are a correct outcome for this run (e.g. 409 "out of stock" in an oversell race):
// not counted in http_req_failed / error rate, reported separately as `expected`.
const expected = (cfg.expected_status || []).map(Number);
if (expected.length) {
  http.setResponseCallback(http.expectedStatuses(...new Set([...expected, { min: 200, max: 399 }])));
}

const counters = {
  ok: new Counter('catchme_ok'),
  expected: new Counter('catchme_expected'),
  s4xx: new Counter('catchme_4xx'),
  s5xx: new Counter('catchme_5xx'),
  neterr: new Counter('catchme_neterr'),
};

export function userSlot() {
  const n = tokens.length || auth.users || 1;
  return (Math.max(__VU, 1) - 1) % n;
}

export function userNumber() {
  return userSlot() + 1 + (auth.user_offset || 0);
}

export function render(tpl, n) {
  if (tpl === undefined || tpl === null) return tpl;
  const user = n !== undefined ? n : userNumber();
  return String(tpl).replace(/\{(\w+)(?::([^}]*))?\}/g, (m, key, arg) => {
    switch (key) {
      case 'n':
      case 'user':
        return String(user);
      case 'vu':
        return String(__VU);
      case 'iter':
        return String(__ITER);
      case 'rand': {
        const [a, b] = String(arg || '1-100').split('-').map(Number);
        return String(a + Math.floor(Math.random() * (b - a + 1)));
      }
      case 'own': {
        const list = (ownMaps[arg] || {})[String(user)] || [];
        if (!list.length) return '0';
        return String(list[(__ITER || 0) % list.length]);
      }
      default:
        return m;
    }
  });
}

export function authHeaders() {
  if (auth.mode === 'none' || auth.mode === 'bypass' || !tokens.length) return {};
  const token = tokens[userSlot()];
  if (auth.token_from === 'cookie') {
    return { Cookie: `${auth.cookie_name || 'SESSION'}=${token}` };
  }
  const scheme = auth.scheme === undefined || auth.scheme === null ? 'Bearer' : auth.scheme;
  return { [auth.header || 'Authorization']: scheme ? `${scheme} ${token}` : token };
}

export function record(res) {
  if (res.status >= 400 && expected.indexOf(res.status) >= 0) counters.expected.add(1);
  else if (res.status === 0) counters.neterr.add(1);
  else if (res.status >= 500) counters.s5xx.add(1);
  else if (res.status >= 400) counters.s4xx.add(1);
  else counters.ok.add(1);
}

export function call(method, path, body, tag) {
  const url = cfg.base_url + render(path);
  const headers = Object.assign(
    { 'Content-Type': cfg.content_type || 'application/json' },
    authHeaders(),
    cfg.headers || {},
  );
  const params = {
    headers,
    tags: { catchme: tag || 'main', name: cfg.name },
    timeout: cfg.timeout || '30s',
  };
  const res = http.request(method, url, body ? render(body) : null, params);
  record(res);
  return res;
}

export function baseOptions(scenarios) {
  return {
    scenarios,
    summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(50)', 'p(95)', 'p(99)'],
    // Always-true thresholds: they only make k6 export tagged sub-metrics in the summary.
    thresholds: {
      'http_req_duration{catchme:main}': ['max>=0'],
      'http_req_failed{catchme:main}': ['rate>=0'],
      'http_reqs{catchme:main}': ['count>=0'],
      'http_req_duration{catchme:auth}': ['max>=0'],
      'http_reqs{catchme:auth}': ['count>=0'],
    },
    setupTimeout: '180s',
    noConnectionReuse: false,
  };
}

function shortLine(data) {
  const tag = cfg.tokens_out ? 'auth' : 'main';
  const d = data.metrics[`http_req_duration{catchme:${tag}}`];
  const r = data.metrics[`http_reqs{catchme:${tag}}`];
  const f = data.metrics[`http_req_failed{catchme:${tag}}`];
  if (!d || !r) return `[catchme] ${cfg.name}: done\n`;
  const p95 = d.values['p(95)'].toFixed(1);
  const err = f ? (f.values.rate * 100).toFixed(2) : '0.00';
  return `[catchme] ${cfg.name}: ${r.values.count} req, p95 ${p95} ms, errors ${err}%\n`;
}

export function summary(data, extraFiles) {
  const out = {};
  out[cfg.out] = JSON.stringify({ metrics: data.metrics, state: data.state });
  Object.assign(out, extraFiles || {});
  out.stdout = shortLine(data);
  return out;
}
