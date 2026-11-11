// catchme auth step: logs in every test user once through the real login API and stores tokens
// for the following runs. Login latency is reported as the auth cost. Tokens are never printed.
import http from 'k6/http';
import { cfg, render, baseOptions, summary, record } from './lib.js';

const auth = cfg.auth;

export const options = baseOptions({
  main: { executor: 'per-vu-iterations', vus: 1, iterations: 1, maxDuration: '10s' },
});

function pick(obj, path) {
  return String(path || 'token')
    .split('.')
    .reduce((o, k) => (o === undefined || o === null ? undefined : o[k]), obj);
}

function extract(res) {
  if (auth.token_from === 'cookie') {
    const c = res.cookies[auth.cookie_name || 'SESSION'];
    return c && c.length ? c[0].value : undefined;
  }
  try {
    return pick(res.json(), auth.token_path);
  } catch (e) {
    return undefined;
  }
}

export function setup() {
  const users = auth.users || 10;
  const offset = auth.user_offset || 0;
  const batchSize = auth.batch || 10;
  const tokens = [];
  for (let start = 1; start <= users; start += batchSize) {
    const reqs = [];
    for (let n = start; n < start + batchSize && n <= users; n++) {
      reqs.push({
        method: auth.method || 'POST',
        url: cfg.base_url + auth.login_path,
        body: render(auth.body, n + offset),
        params: {
          headers: { 'Content-Type': auth.content_type || 'application/json' },
          tags: { catchme: 'auth', name: 'login' },
          redirects: 0,
        },
      });
    }
    const responses = http.batch(reqs);
    responses.forEach((res, i) => {
      record(res);
      const token = extract(res);
      if (!token) {
        throw new Error(
          `login failed for test user #${start + i + offset}: HTTP ${res.status} (check seed.yaml password hash and plan.yaml auth.body/token_path)`,
        );
      }
      tokens.push(token);
    });
  }
  return { count: tokens.length, tokens };
}

export default function () {}

export function handleSummary(data) {
  const extra = {};
  const tokens = (data.setup_data && data.setup_data.tokens) || [];
  extra[cfg.tokens_out] = JSON.stringify(tokens);
  return summary(data, extra);
}
