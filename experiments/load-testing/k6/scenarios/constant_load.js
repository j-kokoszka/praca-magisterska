import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const VUS = __ENV.VUS || 5;
const DURATION = __ENV.DURATION || '30s';

export let options = {
    vus: parseInt(VUS),
    duration: DURATION,
};

export default function () {
    let cpuRes = http.get(`${BASE_URL}/cpu?loops=1000`);
    check(cpuRes, { 'cpu 200': (r) => r.status === 200 });

    let memRes = http.get(`${BASE_URL}/mem?mb=10`);
    check(memRes, { 'mem 200': (r) => r.status === 200 });

    let ioRes = http.get(`${BASE_URL}/io?size=1`);
    check(ioRes, { 'io 200': (r) => r.status === 200 });

    sleep(1);
}

