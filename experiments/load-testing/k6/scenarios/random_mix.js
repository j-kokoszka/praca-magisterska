import http from 'k6/http';
import { sleep } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const VUS = __ENV.VUS || 10;
const DURATION = __ENV.DURATION || '30s';

export let options = {
    vus: parseInt(VUS),
    duration: DURATION,
};

export default function () {
    let rand = Math.random();

    if (rand < 0.5) {
        http.get(`${BASE_URL}/cpu?loops=1000`);
    } else if (rand < 0.8) {
        http.get(`${BASE_URL}/mem?mb=10`);
    } else {
        http.get(`${BASE_URL}/io?size=1`);
    }

    sleep(Math.random() * 1.5);
}

