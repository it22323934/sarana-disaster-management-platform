// Perf gate for the coordinate resolver.
//
// `/admin/resolve` is on the hot path for every citizen report: an incoming SMS, a call,
// a tap in the field app all start by asking which GN division a point falls in. The
// budget is p99 < 20ms at 200 rps, from build file 07.
//
// Run:  k6 run tests/perf/resolve.js
//
// Needs a seeded database and a token. SARANA_TOKEN must carry admin:read; without one
// the run stops immediately rather than measuring 401s, which are fast and meaningless.

import http from 'k6/http';
import { check, fail } from 'k6';
import { Trend } from 'k6/metrics';

const BASE_URL = __ENV.SARANA_BASE_URL || 'http://localhost:8001';
const TOKEN = __ENV.SARANA_TOKEN;

const resolveDuration = new Trend('resolve_duration', true);

// Points spread across several divisions rather than one repeated coordinate. A single
// coordinate would measure the cache and nothing else, and the cache is not what has to
// hold up when reports arrive from across a district at once.
const POINTS = [
  { lat: 7.2906, lng: 80.6337 }, // Kandy
  { lat: 6.9271, lng: 79.8612 }, // Colombo
  { lat: 7.4818, lng: 80.3609 }, // Kurunegala
  { lat: 6.0535, lng: 80.221 }, // Galle
  { lat: 8.3114, lng: 80.4037 }, // Anuradhapura
  { lat: 7.2513, lng: 81.6924 }, // Batticaloa
  { lat: 9.6615, lng: 80.0255 }, // Jaffna
  { lat: 6.9895, lng: 81.0557 }, // Badulla
  { lat: 6.1241, lng: 81.1185 }, // Matara
  { lat: 7.9403, lng: 81.0188 }, // Polonnaruwa
];

export const options = {
  scenarios: {
    resolve: {
      executor: 'constant-arrival-rate',
      rate: 200,
      timeUnit: '1s',
      duration: '60s',
      // Sized for the target rate at a latency well above budget, so the generator is
      // never the bottleneck being measured.
      preAllocatedVUs: 50,
      maxVUs: 200,
    },
  },
  thresholds: {
    // The gate. p99 under 20ms is the requirement; the error ceiling is there so a run
    // cannot pass by failing fast.
    'http_req_duration{expected_response:true}': ['p(99)<20'],
    http_req_failed: ['rate<0.01'],
  },
};

export function setup() {
  if (!TOKEN) {
    fail(
      'SARANA_TOKEN is not set. This gate measures the authorised path, because that is ' +
        'the one citizens actually take.'
    );
  }
  return {};
}

export default function () {
  const point = POINTS[Math.floor(Math.random() * POINTS.length)];
  const url = `${BASE_URL}/api/v1/admin/resolve?lat=${point.lat}&lng=${point.lng}`;

  const response = http.get(url, {
    headers: { Authorization: `Bearer ${TOKEN}` },
    tags: { name: 'resolve' },
  });

  resolveDuration.add(response.timings.duration);

  // A 404 is a correct answer for a point outside every boundary, so both count as
  // success here. Anything else means the endpoint is not doing its job.
  check(response, {
    'resolved or correctly refused': (r) => r.status === 200 || r.status === 404,
    'answered within budget': (r) => r.timings.duration < 20,
  });
}
