import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'https://workload-app-vpa.mgr.kokoszka.cloud';
const VUS = __ENV.VUS || 100;
const DURATION = __ENV.DURATION || '60s';

export let options = {
    vus: parseInt(VUS),
    duration: DURATION,
    // httpReqTimeout: '30s',
};

export default function () {
    let cpuRes = http.get(`${BASE_URL}/cpu?loops=100`);
    check(cpuRes, { 'cpu 200': (r) => r.status === 200 });

}
