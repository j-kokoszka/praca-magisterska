import http from 'k6/http';
import { check, sleep } from 'k6';

/* =========================
 * Konfiguracja (ENV)
 * ========================= */
const BASE_URL   = __ENV.BASE_URL   || 'https://workload-app.mgr.kokoszka.cloud';
const RPS        = parseInt(__ENV.RPS || '3000');
const DURATION   = __ENV.DURATION   || '2m';

const CPU_MS     = parseInt(__ENV.CPU_MS || '1000');
const SLEEP_MS   = parseInt(__ENV.SLEEP_MS || '50');
const PAYLOAD_KB = parseInt(__ENV.PAYLOAD_KB || '1');

const REQ_TIMEOUT = __ENV.REQ_TIMEOUT || '30s';

/* =========================
 * Opcje k6
 * ========================= */
export const options = {
  scenarios: {
    steady_load: {
      executor: 'constant-arrival-rate',
      rate: RPS,
      timeUnit: '1s',
      duration: DURATION,
      preAllocatedVUs: Math.max(10, Math.ceil(RPS / 4)),
      maxVUs: Math.max(50, RPS),
    },
  },

  thresholds: {
    http_req_failed: ['rate<0.01'],              // <1% błędów
    http_req_duration: ['p(95)<2000'],           // p95 < 2s
  },
};

/* =========================
 * Test
 * ========================= */
export default function () {
  const url =
    `${BASE_URL}/cpu` +
    `?loops=${CPU_MS}`;

  const res = http.get(url, {
    timeout: REQ_TIMEOUT,
    tags: {
      scenario: 'steady',
      workload: 'cpu',
    },
  });

  check(res, {
    'status is 200': (r) => r.status === 200,
  });

  // Brak sleep() – rate kontrolowany przez executor
}

