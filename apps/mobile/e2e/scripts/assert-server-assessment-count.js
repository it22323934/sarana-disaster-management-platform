// The assertion that actually matters: how many assessments are on the server.
//
// Everything else in these flows reads the device's own opinion of itself. This reads
// ledger-svc, because the failure the offline core exists to prevent is not "the strip
// said the wrong thing" - it is two payments against one household, or none.
//
// `EXPECTED` comes from the flow. `SARANA_API_URL` and `SARANA_E2E_TOKEN` come from the
// environment the runner passes through; a token is needed because /assessments is
// scoped, and a suite that ran against an unauthenticated endpoint would be testing a
// different server from the one the app talks to.

const base = SARANA_API_URL || 'http://10.0.2.2:8003';
const expected = Number(EXPECTED);

const response = http.get(`${base}/api/v1/assessments?division=${GN_DIVISION}&limit=200`, {
  headers: { Authorization: `Bearer ${SARANA_E2E_TOKEN}` },
});

if (response.status !== 200) {
  throw new Error(
    `ledger-svc answered ${response.status} for the assessment list. The flow cannot ` +
      'tell a sync bug from an unreachable server, so it fails rather than guessing.',
  );
}

const rows = json(response.body);
if (rows.length !== expected) {
  throw new Error(
    `expected ${expected} assessments on the server, found ${rows.length}. ` +
      'More than expected means an operation was applied twice - the idempotency key did ' +
      'not hold. Fewer means work was lost.',
  );
}

output.serverAssessments = rows.length;
