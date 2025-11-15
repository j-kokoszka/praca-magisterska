import http from "k6/http";

export default function () {
  // Send 10 requests to the endpoint
  for (let i = 0; i < 15; i++) {
    http.get("https://workload-app.mgr.kokoszka.cloud/cpu");
  }
}

