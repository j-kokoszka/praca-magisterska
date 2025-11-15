import http from "k6/http";

export const options = {
  vus: 20,          // 10 concurrent virtual users
  duration: "20s",   // run for 5 seconds
};

export default function () {
  http.get("https://workload-app.mgr.kokoszka.cloud/cpu");
}

