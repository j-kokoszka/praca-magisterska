import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate } from 'k6/metrics';

// --- KONFIGURACJA METRYK NIESTANDARDOWYCH ---
// Definiujemy wskaźnik błędów, aby łatwo wygenerować wykresy dostępności (SLA)
export let errorRate = new Rate('errors');

// --- KONFIGURACJA SCENARIUSZA (STAGES) ---
// Odzwierciedla harmonogram z rozdziału 3.2 pracy magisterskiej
export let options = {
  scenarios: {
    spike_test: {
      executor: 'ramping-vus',
      startVUs: 1, // Zaczynamy od 1 użytkownika (linia bazowa)
      stages: [
        // 1. FAZA ROZGRZEWKI (0:00 - 2:00)
        // Utrzymujemy 1 VU, aby system "wstał" i ustabilizował metryki
        { duration: '2m', target: 1 },

        // 2. FAZA SKOKU - SPIKE (2:00 - 3:00)
        // Gwałtowny przyrost ruchu w ciągu 60 sekund (symulacja Flash Crowd)
        { duration: '1m', target: 50 },

        // 3. FAZA PLATEAU (3:00 - 8:00)
        // Utrzymanie wysokiego obciążenia przez 5 minut
        // To tutaj obserwujemy działanie HPA (skalowanie w górę) lub VPA
        { duration: '5m', target: 50 },

        // 4. FAZA WYGASZANIA (8:00 - 10:00)
        // Powrót do stanu zerowego, obserwacja skalowania w dół (scale down)
        { duration: '2m', target: 0 },
      ],
    },
  },
  // Progi akceptacji (opcjonalne, przydatne do CI/CD)
  thresholds: {
    'errors': ['rate<0.01'], // Oczekujemy poniżej 1% błędów (w idealnym świecie)
    'http_req_duration': ['p(95)<2000'], // 95% żądań poniżej 2s
  },
};

// --- ZMIENNE ŚRODOWISKOWE ---
// Adres URL aplikacji testowej (można nadpisać przy uruchomieniu: -e BASE_URL=...)
const BASE_URL = __ENV.BASE_URL || 'https://workload-app-hpa.mgr.kokoszka.cloud';
// Parametr określający "ciężkość" obliczeń (ilość hashowań)
const COMPLEXITY = __ENV.COMPLEXITY || '10000'; 

export default function () {
  // Konstrukcja URL do endpointu generującego obciążenie CPU
  // Zakładamy, że aplikacja przyjmuje parametr sterujący obciążeniem
  const url = `${BASE_URL}/cpu?loops=${COMPLEXITY}`;

  const params = {
    headers: {
      'Content-Type': 'application/json',
      'User-Agent': 'k6-thesis-load-generator',
    },
    // Ustawiamy timeout, aby k6 nie czekał w nieskończoność przy przeciążeniu
    timeout: '10s', 
  };

  // Wykonanie żądania HTTP GET
  let res = http.get(url, params);

  // Weryfikacja odpowiedzi
  const result = check(res, {
    'status is 200': (r) => r.status === 200,
    'response time < 2s': (r) => r.timings.duration < 2000,
  });

  // Rejestracja błędu w metrykach, jeśli status nie jest 200
  // To pozwoli wygenerować wykres Success Rate z Twojej pracy
  errorRate.add(!result || res.status !== 200);

  // Krótka pauza między żądaniami pojedynczego użytkownika (Think Time)
  // Zapobiega sztucznemu DDoS, symuluje realne zachowanie klienta
  sleep(1);
}
