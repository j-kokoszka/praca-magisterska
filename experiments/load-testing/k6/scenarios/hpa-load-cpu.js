import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'https://workload-app-hpa.mgr.kokoszka.cloud';
const VUS = __ENV.VUS || 200;
const DURATION = __ENV.DURATION || '120s';

export let options = {
    vus: parseInt(VUS),
    duration: DURATION,
    // httpReqTimeout: '30s',
};

export default function () {
    let cpuRes = http.get(`${BASE_URL}/cpu?loops=1000`);
    check(cpuRes, { 'cpu 200': (r) => r.status === 200 });

}

