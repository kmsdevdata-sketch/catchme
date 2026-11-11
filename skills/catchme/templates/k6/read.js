// catchme read/load scenario: constant VUs, ramping stages, or fixed iterations per VU.
import { sleep } from 'k6';
import { cfg, call, baseOptions, summary } from './lib.js';

let scenario;
if (cfg.iterations) {
  scenario = {
    executor: 'per-vu-iterations',
    vus: cfg.vus || 1,
    iterations: cfg.iterations,
    maxDuration: cfg.max_duration || '2m',
  };
} else if (cfg.stages) {
  scenario = { executor: 'ramping-vus', startVUs: 0, stages: cfg.stages, gracefulRampDown: '5s' };
} else {
  scenario = { executor: 'constant-vus', vus: cfg.vus || 10, duration: cfg.duration || '30s' };
}

export const options = baseOptions({ main: scenario });

export default function () {
  call(cfg.method || 'GET', cfg.path, cfg.body);
  if (cfg.think_time) sleep(cfg.think_time);
}

export function handleSummary(data) {
  return summary(data);
}
