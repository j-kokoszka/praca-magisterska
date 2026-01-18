import http from 'k6/http';
import { check } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'https://workload-app-hpa.mgr.kokoszka.cloud';

// Zgodnie z sekcją "Konfiguracja eksperymentu" w Twojej pracy:
export let options = {
    stages: [
        // 1. Faza rozgrzewki: 2 minuty stabilnego, małego ruchu
        { duration: '2m', target: 1 }, 
        
        // 2. Faza skoku (Ramp-up): Gwałtowny wzrost w 60s do 50 VU
        { duration: '1m', target: 50 }, 
        
        // 3. Faza plateau: Utrzymanie wysokiego obciążenia przez 5 minut
        // To jest kluczowe! VPA potrzebuje czasu (T_recommender), aby zebrać próbki
        { duration: '5m', target: 50 }, 
        
        // 4. Faza wygaszania: Powrót do 0
        { duration: '2m', target: 0 },
    ],
    // Ważne: ustawienie threshold, aby nie przerywać testu przy błędach 503 (których się spodziewamy przy restarcie Poda)
    thresholds: {
        'http_req_failed': ['rate<1.0'], // Nie przerywaj testu nawet jak 99% to błędy
    },
};

export default function () {
    // loops=1000 - zwiększamy obciążenie per request, aby na pewno nasycić CPU
    // Jeśli 100 to za mało, zwiększ tę wartość eksperymentalnie.
    let cpuRes = http.get(`${BASE_URL}/cpu?loops=10000`);
    
    check(cpuRes, { 
        'status is 200': (r) => r.status === 200,
        // Sprawdzamy czy nie dostajemy 503 (podczas restartu VPA)
        'status is not 503': (r) => r.status !== 503 
    });
}
