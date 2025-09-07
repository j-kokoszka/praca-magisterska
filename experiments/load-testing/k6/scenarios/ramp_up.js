import http from 'k6/http';
import { sleep } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';

export let options = {
    stages: [
        { duration: '10s', target: 5 },
        { duration: '20s', target: 20 },
        { duration: '10s', target: 0 },
    ],
};

export default function () {
    http.get(`${BASE_URL}/cpu?loops=1000`);
    http.get(`${BASE_URL}/mem?mb=20`);
    http.get(`${BASE_URL}/io?size=2`);
    sleep(1);
}

