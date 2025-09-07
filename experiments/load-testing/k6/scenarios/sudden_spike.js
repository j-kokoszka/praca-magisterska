import http from 'k6/http';
import { sleep } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';

export let options = {
    stages: [
        { duration: '5s', target: 5 },
        { duration: '5s', target: 50 },
        { duration: '10s', target: 0 },
    ],
};

export default function () {
    http.get(`${BASE_URL}/cpu?loops=2000`);
    http.get(`${BASE_URL}/mem?mb=50`);
    http.get(`${BASE_URL}/io?size=5`);
    sleep(0.5);
}

