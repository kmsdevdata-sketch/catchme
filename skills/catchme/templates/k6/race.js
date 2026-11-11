// catchme race scenario: N VUs each send one request at (almost) the same moment.
// Verdict comes from invariants.yaml, not from status codes.
import { cfg, call, baseOptions, summary } from './lib.js';

const vus = cfg.vus || 100;

export const options = baseOptions({
  main: {
    executor: 'per-vu-iterations',
    vus,
    iterations: cfg.iterations || 1,
    maxDuration: cfg.max_duration || '2m',
  },
});

export default function () {
  call(cfg.method || 'POST', cfg.path, cfg.body);
}

export function handleSummary(data) {
  return summary(data);
}
