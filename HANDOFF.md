# SARANA — handoff

State of the build as of 2026-09-02. Written for whoever picks this up next.

Read [RUNNING.md](RUNNING.md) first if you have not booted the stack.

---

## Where the build has got to

The repository is organised around 30 numbered build files in `.claude/`. Progress is
strictly sequential. **Files 03-20 are complete.** Every route the brief names is built
and tested end to end in a browser; no route renders a "not built" screen. Closing file 20
needed five read endpoints the platform had data for and no way to return, and it turned up
two finished screens that no user could reach. The next work is 21.

| File | Area | State |
|---|---|---|
| 03 | Monorepo scaffold | Done |
| 04 | Data model | Done |
| 05 | Auth / RBAC | Done |
| 06 | Event backbone | Done |
| 07 | core-api | Done — 29 endpoints |
| 08 | incident-svc | Done — 20 endpoints |
| 09 | alerting-svc | Done — 15 endpoints. Targeting is a placeholder. |
| 10 | ledger-svc | Done — 28 endpoints, publicly verifiable ledger |
| 11 | gov-mock | Done — 31 endpoints, 7 mocked systems, inbound simulator |
| 12 | LangGraph runtime | Done — runtime, HTTP surface, event triggers, eval harness |
| 13 | Forecast & impact agent | Done — rule-threshold engine, Ditwah replay, eval |
| 14 | Warning dissemination agent | Done — template selection, targeting, CAP, gaps |
| 15 | Intake & verification agent | Done — extraction, geolocation, dedup. No adapters. |
| 16 | Triage & dispatch agent | Done — scoring, OR-Tools routing, the gate. No adapters. |
| 17 | Aid ledger & anomaly agent | Done — exposure-normalised detectors. No adapters. |
| 18 | Supervisor & HITL | Done — routing table, both gates, conflicts. No adapters. |
| 19 | Design system | Done — tokens, 3-script type, 34 components, 4 CI gates |
| **20** | **Ops console** | **Done — 25 routes, 60 static pages, 93 e2e tests** |
| **21** | **Public dashboard** | **Scaffold only** |
| 22–24 | Mobile (foundation, citizen, field companion) | Scaffold only |
| 25–29 | AWS, observability, security, seed, CI | Not started |
| 30 | Demo script | Not started |

On the TypeScript side, **329 tests pass**: 64 unit and 33 axe-over-every-story in
`packages/ui`, 54 in `packages/ts-shared`, and in `apps/web-ops` 59 unit, 75 axe across
**25 screens x three locales**, and **93 Playwright tests in a real Chromium**. `pnpm lint`,
`pnpm typecheck` and all seven of file 19's Definition of Done commands are clean. Of file
20's four, three pass; the fourth reports a measured LCP that the stack cannot meet, and
says so with the evidence rather than passing quietly.

On the Python side, untouched by file 19:
**1,663 tests passing, 2 skipped** (1,665 collected across `tests/` and
`packages/py-shared/tests`). `ruff check`, `ruff format --check` and `mypy` (342
source files) all clean. File 14 added 122 (76 under `tests/agents/warning`, 46 for the
SMS segment gate); file 15 added 79 under `tests/agents/intake`; file 16 added 79 under
`tests/agents/triage`; file 17 added 74 under `tests/agents/ledger_anomaly`; file 18
added 51 under `tests/agents/supervisor` and 7 under `tests/e2e`; plus 15 for the
dispatch-gate resumer under `tests/incident`. File 20 added 7 under
`tests/incident/test_plan_reasoning.py`, 26 under `tests/auth/test_console_scopes.py` and 3
under `tests/ledger/test_console_vocabularies.py` — the last two are cross-language
vocabulary gates, checking the console's scope names and enumerations against the Python
ones it cannot import.

```
core-api        33 endpoints,  7,171 lines
incident-svc    20 endpoints,  4,657 lines
alerting-svc    15 endpoints,  4,177 lines
ledger-svc      30 endpoints,  7,149 lines
gov-mock        31 endpoints,  4,865 lines   <- 7 mocked systems + control plane
agent-svc        6 endpoints, 21,543 lines   <- runtime, all 6 agents + supervisor
```

The jump from 680 is file 11's suite plus `tests/alerting/test_seeded_templates.py`, which
had never run: it imports `tools.seed.templates`, and pytest's `--import-mode=importlib`
does not put the repo root on `sys.path`, so the module failed to import and took the whole
collection down with it. `pythonpath = ["."]` in `pyproject.toml` fixes it. Worth knowing
because the symptom was a *collection* error, which reads like a broken test file rather
than 13 tests that had silently never executed.

---

## The one thing carried forward from file 09

File 09 is otherwise complete. This is the piece that was left, and it is load-bearing.

### Real targeting — done

`_targets_for()` reads `admin.household` through core-api under a credential holding
`household:contact_read` and nothing else. Before this, it returned one synthetic target
per GN division: a division of 400 households counted as **one person** in every delivery
figure the platform published, so "1,203 unconfirmed, 865 no channel available" described
an area with four synthetic people in it.

Three decisions inside it:

**Unreachable households are targeted anyway.** A household with no contact number comes
back with no hash, gets a stable identity keyed on its own id, and the fan-out records
`NO_CHANNEL` against it. They are the people who need a vehicle with a loudhailer, and
`/alerts/{id}/delivery/gaps` can only name them if targeting keeps them. Filtering them out
would report a division as fully covered when a sixth of it cannot be reached.

**Two households sharing a handset are one target.** Common in a village, and sending the
same evacuation order twice to one phone is noise at the moment attention is scarcest. The
delivery accounting already counted by contact hash, so they collapsed in the figures
either way — deduplicating here means the message is *sent* once rather than merely counted
once. Unreachable households key on their own id and never collapse, because each one is a
separate person somebody has to go and find.

**A directory outage stops the dispatch.** `DirectoryUnavailable` propagates rather than
being caught. A fan-out over whichever households happened to resolve, reported as a
completed dispatch, is worse than one that refused: the alert looks sent and the people it
missed are invisible.

`GET /admin/households/contacts` is the bulk read behind it — paged, area-scoped, capped at
200 divisions per request, and behind the same scope as the single-household lookup. A
national alert covers ~14,000 divisions and pages through them; one query over all of them
would hold a connection open during the single event when it must not.

### The twelve templates load as DRAFT, and that is deliberate

`make seed` now creates all twelve, every one `DRAFT` with no reviewer signatures. Before
any alert can be dispatched a human must sign each language through
`POST /templates/{id}/review` and then `POST /templates/{id}/publish`.

That is the gate working. Do not seed them as PUBLISHED to make a demo flow smoothly —
it would put twelve machine-translated life-safety messages one API call from a district.

### What file 09 delivered

- `domain/cap.py` — CAP 1.2 documents, three `<info>` blocks, structural validation
- `domain/templates.py` — trilingual review gate, parameter substitution, soft third gate
- `domain/delivery.py` — fan-out, delivery summary, gaps, dry run
- `adapters/channels/` — six adapters: SMS, USSD, push, in-app, LoRa (simulated), manual
- `repo/queries.py`, `api/deps.py`
- `api/v1/alerts.py` — draft, signoff, dispatch, cancel, list, `cap.xml`, `feed.atom`,
  `delivery`, `delivery/gaps`
- `api/v1/templates.py` — create, list, review, publish
- `api/internal/dlr.py` — the delivery receipt webhook
- `tools/cap_validate.py` — the DoD gate, passing on a generated artefact

---

## File 10 is done — what was built, and the four decisions inside it

28 endpoints. The chain from a GN officer's offline assessment through calculation,
approval, the disbursement gate, the hash-chained ledger entry, the daily Merkle anchor and
the citizen's confirmation SMS is complete and end-to-end tested.

The parts worth knowing before you touch any of it:

### `/ledger/public` is per-entry, not aggregated

The brief says the feed is "anonymised, aggregated" *and* that `sarana-verify` "recomputes
every entry hash" from it. Those cannot both hold: a total is a claim, and recomputing a
hash chain needs the entries the chain is over. So the feed is per-entry and anonymised —
no household, no GN division, no assessment reference, no coordinate, no name — and the
aggregate the dashboard wants is a second endpoint, `/api/v1/public/ledger-summary`.

`released_by` and `entitlement_id` stay in the public feed. Both are UUIDs with no public
resolver, and a ledger that does not commit to who released public money is not an
accountability record.

### One definition of a ledger entry, in `domain/ledger_entry.py`

Three things have to agree byte for byte or an honest ledger fails verification: what
`chain_writer` hashes, what `/ledger/public` publishes, and what the anchor job builds the
tree over. They all call `public_entry()`. `released_at` is rendered to a **string** there,
because `+00:00` versus `Z` from a JSON serialiser is enough to break every hash in the
feed, and it would break at deployment rather than in a test.

`tests/ledger/test_public_feed.py` asserts the agreement, including that the verifier can
parse the API's actual response envelopes. That last test exists because `date` and
`anchor_date` diverged between the two and nothing failed — every other test built its own
anchor dict, so the mismatch would have surfaced the first time a journalist ran the tool.

### `seq` and `anchor_date` are outside the hash

`HASH_FIELDS` is four fields, not two. `seq` is a database identity column that is not
known until the row is written, so an entry could not be hashed before insertion if the
hash covered it; the chain linkage already fixes the order. `anchor_date` is a timezone
rendering of `released_at`, so committing to it would make the hash depend on a rendering
rather than a fact. `tools/sarana-verify` excludes the same four and
`tests/ledger/test_chain_agreement.py` asserts the two lists are one set.

Note `link()` in the shared module strips only `OUTPUT_FIELDS`, the two hashes it rewrites.
Conflating the two sets made it drop `seq` from the record it returned.

### The append-only table has exactly one opening (migration 0008)

`aid.disbursement` had `citizen_confirmed`, `citizen_confirmed_at` and
`citizen_confirm_channel` and no way to ever set them — UPDATE was revoked from
`sarana_app` and trigger-blocked for everyone including the owner. Three columns that
permanently read false, which under-reports every payment that actually arrived.

0008 replaces the blanket trigger with `aid.disbursement_confirmation_only()`, which
compares every other column and refuses the write if any of them moved, and forbids a
confirmation going true → false. The grant is column-level. The confirmation columns are
outside the hashed payload, so answering an SMS cannot change a published hash.

If you add a column to `aid.disbursement`, add it to `IMMUTABLE_COLUMNS` in that migration.
The list is explicit rather than derived so an addition has to be considered.

### Still placeholder, and honest about it

- **Anchors are not externally stored** without an object store. `NullAnchorStore` returns
  `None` for the URI and logs `anchor_not_externally_stored` rather than a plausible
  `s3://` string. An anchor claiming a compliance lock it does not have would be a lie at
  the exact point somebody relies on it. Wiring MinIO or S3 is the remaining work.
- **Every payment rail is a mock**, every reference starts `MOCK-`, and
  `adapters/rails.py` deliberately has no failure-injection knob — a rail that sometimes
  fails on a demo has its failures explained away as the demo.
- **`aid.device_sync_cursor`** (migration 0007) is new: the per-device `seq` cursor the gap
  rule needs. Without it, 8-9-10 after 7 was lost is indistinguishable from the next three
  operations in order.

### Two schema contradictions found and fixed

Both were live defects, not tidying:

1. **Two district approval thresholds.** `domain/approval.py` said LKR 500,000;
   `domain/disbursement_gate.py` said LKR 100,000. An entitlement between them read as
   fully approved and was then refused at release for a signature nobody had been asked
   for. The gate now imports the constant.
2. **`aid.ledger_anchor` had no `prev_anchor_hash`** (fixed in 0009). ADR-005 chains the
   anchors so a removed *day* is as detectable as an altered row; the value was computed,
   written into the S3 object, and then dropped. A verifier could check every root and
   still miss a missing Tuesday.

### Resolved: the trigger and the verifier now agree

*Kept here because the reasoning matters, and because the same trap exists anywhere else a
hash is computed in SQL.*

Entries written before migration `ledger_svc_0006` could not be verified by
`sarana-verify` at all. Build file 10 specifies:

```
entry_hash = SHA256( canonical_json(entry_without_hashes) || prev_hash )   # RFC 8785
```

`public.sarana_hash_chain()`, shipped in file 04, computes something else:

```sql
payload := (to_jsonb(NEW) - 'entry_hash')::text;   -- PostgreSQL's jsonb text form
NEW.entry_hash := encode(sha256(convert_to(payload, 'UTF8')), 'hex');
```

Three concrete differences, all demonstrated against the running database:

| | PostgreSQL `jsonb::text` | RFC 8785 |
|---|---|---|
| Key order | by (length, bytes) | by UTF-16 code unit |
| Whitespace | `{"a": 2}` | `{"a":2}` |
| `prev_hash` | inside the hashed payload | appended after it |

The ordering difference is not theoretical:

```
postgres:  {"z": 1, "aa": 2}
RFC 8785:  {"aa":2,"z":1}
```

**What was done.** Implementing RFC 8785 in plpgsql would be a great deal of delicate SQL
to reproduce a standard that already has a tested implementation, so the responsibilities
were split instead:

- The **application** computes `entry_hash` via `sarana_shared.crypto.chain`, which is the
  same code path `sarana-verify` recomputes.
- The **trigger** (`sarana_enforce_supplied_chain`) stopped computing the hash. It now
  enforces what only the database can: that the supplied `prev_hash` really is the current
  tail, under an advisory lock, and that a well-formed hash came with it.

It deliberately does **not** fill `prev_hash` when missing, which was a flaw in the first
attempt at this: `prev_hash` is an input to `entry_hash`, so filling it afterwards leaves a
stored hash describing a predecessor the row does not claim. Appending is therefore
read-tail → compute → insert, retrying if another writer wins the race. That is
`ledger_svc.repo.chain_writer.append()`, and `tests/schema/factories.append_chained()` is
the same pattern for tests.

An entry arriving with no hash is **refused**, not given a locally-computed one. A hash
nobody can reproduce is worse than none — it looks verifiable and is not.

`tests/ledger/test_chain_agreement.py` asserts the two ends agree, and would have caught
the original defect.

**`audit.audit_entry` deliberately keeps `sarana_hash_chain`.** That chain is verified by
core-api's `/audit/verify`, which recomputes with the same SQL expression, so the two agree
with each other. It is never published for outside verification, so it does not need RFC
8785, and changing it would mean changing that verifier in lockstep for no gain. A test
asserts this stays a decision rather than drifting into an oversight.

## File 11 is done — the seven mocks, and the decisions inside them

35 endpoints across seven mocked systems, a control plane, and an inbound SMS/USSD
simulator page. Every agent in files 12–18 depends on this, which is why it comes first.

The adapter layer is the deliverable that matters most:
`packages/py-shared/src/sarana_shared/adapters/gov/`. Each system appears three times — a
**Protocol** (what SARANA needs), a **MockClient** (HTTP to gov-mock), and a **RealClient**
whose every method raises `NotImplementedError` naming the endpoint, the credential and the
agreement still to be negotiated. Nothing imports the mock directly.

`integration_register()` prints the whole outstanding negotiation list. It is generated from
the same records the stubs raise from, so it cannot drift the way a document would. Print it
when somebody asks what SARANA needs from which agency.

### The routers mount at the root, not under `/api/v1`

`/met/v1/warnings`, `/ndrsc/v1/claims`, `/telco/v1/sms/send`. Every other service serves one
versioned prefix; this one stands in for seven systems that are not SARANA, and each has its
own URL shape. Normalising them would make the mock tidier and would hide exactly what has
to be true for the real swap to be a configuration change.

The `api/v1/`, `repo/`, `domain/` and `adapters/` scaffold packages were removed. gov-mock
owns no tables and has no domain of its own — it stands in for other people's.

### Both mock markers are checked by the client, not trusted from the server

Every response carries `X-Sarana-Mock: true`; every JSON body carries `"source": "MOCK"`;
the XML feed carries `source="MOCK"` on its root element. `MockGovClient` **refuses** a
response without them.

That check is the point. Without it, pointing `SARANA_GOV_MOCK_URL` at a real agency
endpoint would work, and nobody would find out until real warnings appeared in a demo — or
a demo's synthetic rainfall reached something that mattered. The header is stamped by
middleware mounted outermost, so it also covers 404s, validation failures and the failures
chaos injects: the guarantee has no exceptions to reason about.

### One clock, pinned, and every mock reads it

`gov_mock.clock.SimulatedClock`. Nothing reads the wall clock — `api/deps.simulated_now` is
the only source of "now", and a route calling `datetime.now()` would opt out of both the
scenario driver and the staleness injection.

It is **pinned by default**: `now()` returns the same instant until somebody advances it, so
every figure is a pure function of `(seed, entity, offset)`. The same scenario at T+6h
produces the same rainfall at the same stations on every machine and every replay. `speed`
is the seam for file 28's driver; it is 0 here because a test that has to sleep to observe a
value will be flaky on somebody else's laptop.

The escalation this produces is the arc the whole platform needs:

```
T-72h  Yellow advisory     Kandy   4.8mm   no bulletins       nobody displaced
T-24h  Amber               Kandy 113mm     12 DS on WATCH
T-6h   Red                 Kandy 155mm     28 DS EVACUATE     evacuation orders out
T+6h   Red (peak)          Kandy 131mm     32 DS EVACUATE     13,680 displaced
T+24h  Red, subsiding      Kandy  54mm     bulletins easing   34,863 displaced
T+48h  stood down          Kandy   9mm     no bulletins       42,172 displaced
T+120h                                                        orders lifted
```

### Rainfall falls off away from the track, and that is load-bearing

`gov_mock.data.met.exposure_at` is a 2D Gaussian around the landfall point. The first
version had a flat national peak with an east-coast multiplier, and the result was that
every district in the country crossed every threshold at once — NBRO issued 25 identical
EVACUATE bulletins, including for Colombo. That looks like a working escalation and is
actually a national deluge no targeting logic can be tested against.

`dmc.AFFECTED_DISTRICTS` is now **derived** from the same model rather than hand-listed, so
moving the track cannot leave shelters filling in districts the rain never reached.

### Chaos is on by default, and the control plane is exempt

5% each of timeout, error, malformed and stale, per build file 11. Timeout genuinely holds
the connection rather than answering a fast 504 — a client's timeout handling is only
exercised by something that actually fails to answer. A gateway 504 now maps to `GovTimeout`
rather than a generic refusal, because a gateway reporting an upstream timeout is the same
fact as our own read timeout expiring, and a caller deciding whether a retry is safe must
not have to know which side noticed.

`/mock/v1/*` is never injected into. Injecting failures into the endpoint that turns
injection off would make 100% chaos unrecoverable, and the first person to try it would have
to restart the container mid-demo.

**Stale is the one to worry about.** A well-formed answer computed three hours ago, where
nothing about the response looks wrong. It is the injection most likely to be believed and
the only one that cannot be caught by checking a status code.

### A derived outcome needs a digest, not a checksum

`gov_mock.data.derive`. Several mocks decide something once and must keep deciding it the
same way forever — whether a transfer fails, whether the CMS returns a claim, whether a NIC
is on the register. None may be *drawn*: a transfer that fails on one poll and settles on
the next is undebuggable, and a household told two different things about the same card is
far worse than a consistent gap.

The first implementation derived them from `sum(ord(c) for c in reference) % 1000`. That
looks fine and clusters badly: `SARANA-PAY-0000` through `SARANA-PAY-0499` span about twenty
consecutive values, because a fixed prefix contributes a constant and four digits cannot
move the total far. The result was not "3% of transfers fail" but "3% of reference
*namespaces* fail" — a whole batch shares one fate, decided by whichever prefix somebody
chose. A test looking for one failing transfer in five hundred found none.

A SHA-256 bucket has no such structure. Used for its distribution, not for any security
property; the `salt` keeps independent decisions about the same identifier independent, so a
NIC's presence on the register does not correlate with whether that household's payment
fails.

### The registers are independent copies, and a test holds them together

gov-mock keeps its own district table, its own landslide zonation and its own network
inventory, because a real agency does. Independent copies are the right shape — but only if
something checks them. `tests/gov_mock/test_registers_agree.py` asserts, in both directions,
that the mock and `data/seed` agree on district codes, district names, GN code shapes,
`landslide_zone` and `cell_coverage_pct`.

The failure this prevents is quiet: the mock says a division is in zone 2 while
`admin.gn_division` says zone 4, an agent reasons about one hazard map, a warning is issued
off the other, and nothing anywhere reports an error.

Same pattern as the vocabulary tests. Write one whenever two systems hold the same fact.

### NBRO's thresholds are stand-ins, and every record says so

`rain_thresholds()` is what the rule-based fallback forecast (file 13) will key off. The
figures are served rather than embedded in agent code so that replacing them with NBRO's
real ones is a data change, not a code change somewhere nobody remembers to look.

Every `ThresholdSet` carries a `provenance` string beginning `SYNTHETIC`, and
`ThresholdSet.is_official` reports False everywhere they are used. **Getting the real
thresholds in writing is the highest-value item on the integration register.** Do not
quietly delete the provenance string to make a dashboard look tidier.

### NDRSC: SARANA pushes, the CMS is the system of record

Read `sarana_shared.adapters.gov.ndrsc`'s module docstring before touching any of it. The
direction is the design, and it is not a technical preference: a system that models itself
as the authority on who gets compensated is asking NDRSC to surrender its own register, and
it does not get adopted. `submit_claim` pushes, `claim_status` reads back, and there is
deliberately no method that edits or withdraws a submitted claim — a correction is a new
claim referencing the old one.

### Names are distributed by district, and the weights are not demographic data

`gov_mock.data.names`. A demo where every household in Batticaloa has a Sinhala name is
wrong, and it is wrong in a way that tells Tamil and Muslim communities the system was not
built with them in mind. Three naming conventions are modelled, each by its own real rule
rather than one template with the word list swapped.

`COMPOSITION` holds approximate district shares rounded from the 2012 census. They exist for
exactly one purpose: weighting which convention a generated name follows. **They are not
demographic data and nothing may present them as such** — no chart, no report, no
"population by ethnicity" panel.

### gov-mock owns no tables, and runs as one replica

Recorded state — claims, transfers, messages, headcounts — lives in memory
(`gov_mock.state`). Giving an external-system mock tables inside the platform's own database
would put other people's records inside the boundary SARANA is audited on. Restarting the
container is meant to be how you reset it.

The consequence, stated so nobody spends an afternoon on it: **do not scale this service**.
Two replicas would disagree about a claim's status and a poller would watch it flip.

### Still placeholder, and honest about it

- **The whole payment loop is wired.** A failed transfer produces a chained reversal, a
  grievance, a reopened entitlement, and an SMS telling the household what to do. The
  confirmation message after a successful release is sent too — it never had been.
- **The payment webhook is registered and never called.** Delivering a callback would mean
  the mock reaching into the platform on its own schedule, which makes a scenario replay
  depend on network timing. The ledger polls instead.
- **Met observations have no history.** `from`/`to` are accepted and ignored, and the
  response says so in `window_supported: false` rather than quietly reinterpreting a window
  as "now".
- **Two scenarios only**, `ditwah_kandy` and `quiet`. File 28 adds the rest. `quiet` exists
  so "nothing fires when nothing is happening" is testable — as easy a bug to ship as
  missing a cyclone, and much harder to notice.

### What this unblocks

**Alert targeting — the file 09 carry-forward — is now unblocked on the data side.**
`/hhreg/v1/households` serves households by GN division, and `/telco/v1/coverage` serves
per-division coverage that degrades as cell sites lose power. What is still missing is the
platform's own `admin.household` read behind core-api, which is the service-credential
problem below, not a data problem.

---

## The compensating entry, and the four decisions inside it

The loose end between files 10 and 11, now closed. About three transfers in a hundred fail
*after* the rail accepted them, by which time `aid.disbursement` has recorded a release,
hashed it and published it. Nothing in the platform used to find out.

`ledger_svc.workers.settlement` now asks the rail about every payment whose outcome is
still unknown, and when one has come back it writes a compensating entry, raises the
household's grievance and reopens the entitlement, in one transaction.

### A separate table, not a negative-amount disbursement

`aid.disbursement_reversal`, on its own hash chain. Three reasons, in order of weight:

`ledger_svc.domain.ledger_entry` defines the one field set that is hashed *and* published
*and* anchored. Adding a field to it changes the recomputed hash of **every entry ever
written**, including the ones written before the field existed, and breaks
`tools/sarana-verify` against all of history. A reversal with its own payload shape cannot
touch that.

`aid.disbursement` constrains `amount_lkr_cents > 0` and held one row per entitlement.
Both are real invariants that stop a double-pay bug, and neither should be relaxed to model
a rare correction.

And it is how double-entry bookkeeping has always recorded one.

`disbursement_id` is **inside** the reversal's hashed payload, so a reversal cannot later
be denied or quietly re-pointed at a different payment. That is the difference between a
compensating entry and a note in a file.

### `reversed` is published and not hashed, and the exclusion list is now five

The public feed carries `reversed` on each entry, because publishing a released payment
with no hint that the money came back is the sort of true-but-misleading number a
transparency feed exists to prevent.

It is **outside** the hash, for the same reason the citizen confirmation columns are: the
entry means "this money was released, on this date, by this person", and that stays true.
So `HASH_FIELDS` is now `(prev_hash, entry_hash, seq, anchor_date, reversed)` in all three
places — `sarana_shared.crypto.chain`, `ledger_svc.domain.ledger_entry.NON_PAYLOAD_FIELDS`
and `tools/sarana-verify`. `tests/ledger/test_chain_agreement.py` asserts they are one set;
`tests/ledger/test_public_feed.py` asserts the field is published, excluded, and absent
from `public_entry()`.

**This is the trap that cost a day in file 10 and would have cost another here.** A field
added to the published feed and not to the exclusion list makes every honest entry fail
verification, and it fails at deployment rather than in a test.

`sarana-verify` gained `--reversals` and cross-checks the two feeds: a reversal against a
disbursement that is not published, an amount that does not match, or an entry flagged
`reversed` with no compensating entry. That last one matters because `reversed` is the one
field on an entry an operator could change without breaking a hash.

### A reversed payment frees the entitlement to be paid again

`uq_disbursement_entitlement` became a partial unique index over live rows only
(`WHERE reversed_at IS NULL`), and `already_released` in the release gate now means
"released and not reversed".

Without that, reversing a bounced payment would permanently bar the household from money
they are owed — which makes the correction a worse outcome than leaving the bad record
standing. `tests/ledger/test_reversal.py` asserts both halves: a reversed entitlement can
be paid again, and two *live* payments for one entitlement are still refused.

### The grievance is raised before the entry, and `SYSTEM` is a real channel

The first version appended the reversal and then updated `grievance_id` onto it. The
append-only trigger refused, correctly — an editable reversal is a way to un-fail a
payment. Rather than open a hole in that guarantee for a case number, the order was
reversed: the case is opened first and `grievance_id` is `NOT NULL`. A reversal that could
exist without one is a household nobody told, and on an append-only table it could never be
filled in afterwards.

`GRIEVANCE_CHANNELS` gained `SYSTEM`. Nobody replied NO — a bank returned the money and the
household is at home believing they have been paid. Recording that as `SMS` would put a
falsehood in the field an officer reads to decide how to reply, and would make "how are
citizens actually reaching us?" unanswerable from the data.

The grievance text comes from `domain.reversal.REASON_TEXT`, in all three languages, and is
written as an instruction rather than a diagnosis. A test asserts the English never contains
the enum value: `ACCOUNT_DORMANT` tells a family nothing; "visit your bank branch to
reactivate it" tells them what to do on Monday.

### What the poller will and will not do

- **An unreachable rail reverses nothing.** `GovUpstreamError` leaves the payment alone for
  the next pass. A poller reading a timeout as a failed payment would reverse money that is
  on its way and do it to every household in the same pass, turning one bank outage into a
  national incident inside the platform. This is the most important test in
  `tests/ledger/test_settlement_poller.py`.
- **A reference the rail has never heard of reverses nothing.** The ledger and the rail
  disagreeing is a reconciliation case for a person; taking money off the books on the
  strength of an *absence* is the wrong direction.
- **It never retries the transfer.** Re-sending to an account that just rejected it
  produces a second failure and a ledger claiming two payments. Paying again is a new
  release through the human gate.
- **A machine cannot record a human judgement.** `MACHINE_REPORTABLE` excludes
  `ADMINISTRATIVE_ERROR` and `DUPLICATE_PAYMENT` — those are decisions about what somebody
  did, not observations of what a bank returned, and a system that can make them by itself
  can take money off the books with nobody accountable.
- **`SARANA_LEDGER_SETTLEMENT_POLL_SECONDS=0` disables it**, which is what tooling and
  one-shot runs want.

`tests/ledger/test_vocabularies.py` is the seam test between the two files: every failure
reason the mock rail can report is one the schema will store, the adapter's enum has not
narrowed it, and a worker is permitted to record all of them. A reason the rail invents and
the database rejects would be a 500 on the one path that only runs when a household's
payment has already failed.

---

## Machine credentials, and the consumer that tells households about their money

Two things closed together, because the second was blocked on the first.

### The long-lived service token is gone

`SARANA_INCIDENT_SERVICE_TOKEN` was a never-expiring `SERVICE` token, minted by a script and
pasted into an environment file. It could not be rotated without a redeploy, could not be
revoked at all, granted every scope the SERVICE role had whether the caller needed them or
not, and anybody who read the file held it forever. It was documented as a workaround from
the day it was written.

`POST /api/v1/auth/token` replaces it with a client-credentials grant against
`admin.service_client`. Four properties, each of them one of the things that was wrong:

- **Short-lived.** Fifteen minutes, the same as a person's. There is deliberately no
  "machines are different" exemption, because that exemption is how a permanent credential
  comes back. Revoking a client takes effect within the quarter hour.
- **Revocable.** `active = false` and the next grant fails.
- **Least privilege.** `allowed_scopes` narrows a credential to a subset of the SERVICE
  role. incident-svc holds `admin:read` and nothing else; `household:contact_read` is held
  by alerting-svc and — since file 14 — by agent-svc, and by nothing else; gov-mock's
  gateway holds `incident:write` and cannot read anything.
- **The secret is never stored.** Argon2id, shown once at provisioning, not recoverable.

**The ceiling is in code, not in the database.** A client gets the intersection of what it
asked for, what it was configured with, and what `Role.SERVICE` grants — and the widest of
those three is `ROLE_SCOPES`. A row written straight into `admin.service_client` asking for
`ledger:read` produces a credential that cannot be turned into a legal grant at all, which
is the property that matters if the database is ever compromised.

**Human gates are closed twice.** `Principal.can` already refuses `disbursement:release`
and `dispatch:commit` to every machine principal. `ServiceClientConfig` refuses to be
*configured* with one as well, and that check runs before the ceiling check so the error
names the real problem. There is no row in that table that releases money.

Every failure — unknown client, revoked client, wrong secret, unsupported grant type —
returns the same refusal, because distinguishing them turns the endpoint into a way of
enumerating which services exist and which credentials are live. A test asserts the three
messages are identical.

Provision with `make service-clients`. The secrets print once; `--rotate` issues new ones
and the old ones stop working on the next grant.

### `household:contact_read` is its own scope

`/admin/households` deliberately selects no column that identifies a person — "nothing to
redact is a stronger guarantee than redacting". Folding contact lookup into `admin:read`
would have quietly widened every credential that only ever needed the hierarchy, so
`GET /admin/households/{id}/contact` sits behind its own scope and returns a keyed HMAC,
never a number. The gateway resolves that hash to a real address at the edge.

Absent and out-of-scope return the same 404. Confirming that a household exists but belongs
to another district is a disclosure in itself.

### alerting-svc consumed nothing at all

This was the surprise. `ledger-svc` publishes `disbursement.released` with a comment saying
"alerting-svc listens for this and sends the confirmation SMS" — and alerting-svc ran no
consumer. So the YES/NO reply, which the ledger's own module docstring calls the cheapest
and highest-signal error detector in the system and the only independent evidence that
money reached anybody, **had never once been asked for**.

`PaymentNoticeWorker` now handles both payment events:

- `disbursement.released` → "LKR 47,500 has been sent to your account. Reply YES if it
  arrived, or NO if it did not." A NO already became a grievance automatically; now
  something actually asks the question.
- `disbursement.reversed` → the amount, the specific remedy in the household's own
  language, and the case reference.

Three rules, each guarding a failure mode:

- **A household with no phone is an acknowledged gap.** Not everybody has one, and
  redelivering the event will not give them one. What it needs is an officer.
- **A directory outage is *not* acknowledged.** The event comes back. Recording "we could
  not ask who this is" as "this person cannot be reached" would silently drop a household's
  message and make the coverage figures wrong in the direction that looks fine. That is the
  most important test in `tests/alerting/test_payment_notices.py`.
- **`side_effect_free=False`.** A replay handed to this consumer would message every
  household about a payment they were told about weeks ago.

### Two contract bugs the consumer found

Both had been latent because nothing consumed these events.

**`AidDisbursementReleased` did not describe what was published.** The contract listed
`released_at`, which is never sent, and omitted `household_id`, `payment_ref`,
`confirmation_required` and `simulated`, which always are. `EventPayload` sets
`extra="forbid"`, so the first consumer to call `parse_payload` would have failed outright
— which is exactly what happened when one was written.

**My own reversal event had two shapes.** The settlement poller and the internal endpoint
published different field sets for the same event type. A consumer would have worked
against one path and failed against the other. Both now publish the same payload, and a
test parses both against the registered contract.

### Reversal reasons moved to `sarana_shared`

`ReversalReason` and its trilingual text now live in
`sarana_shared.domain.reversal_reasons`, because three things need the same answer and none
may import another's code: gov-mock's rail reports the reason, ledger-svc stores it and puts
the text in a grievance, alerting-svc renders it into the SMS. alerting-svc was briefly
importing `ledger_svc.domain.reversal` directly, which is a layering violation that mypy
was happy to allow.

A family told one thing by SMS and something else at the Divisional Secretariat counter is
a family that stops believing either.

---

## File 12 is done — the agent runtime, and the decisions inside it

`services/agent-svc` now has a working LangGraph runtime, an HTTP surface, event-triggered
runs and an evaluation harness. One reference agent, `noop`, exercises all of it without
touching a model provider.

```bash
uv run pytest tests/agent_svc services/agent-svc/tests      # 123 tests
uv run pytest tests/agents/forecast                        # 81 tests
uv run python -m agent_svc.runtime.eval --agent noop --fixtures data/fixtures/smoke
make eval AGENT=noop                                       # writes artifacts/eval/
```

### A node re-executes from the top when it resumes — plan the graph around it

This is the single fact that decides how every agent in files 13-18 is shaped. When a node
calls `interrupt()` and a person answers days later, LangGraph **re-runs that node from its
first line**. Everything above the `interrupt()` happens twice.

So the side effect goes in a *separate node downstream of the interrupt*, never after it in
the same function. `agents/noop/graph.py` is laid out that way deliberately —
`approve` pauses, `record` writes the audit entry — and the comment saying why is in the
node itself, because the next person to add a line to an approving node will not have read
this file.

`tests/agent_svc/runtime/test_interrupt_resume.py` proves both halves: the pre-interrupt
code ran twice and the post-interrupt side effect ran once.

### The version numbers in the build file do not resolve

File 12 pins `langgraph-checkpoint-postgres ^2.0`. That does not install: the 2.x line
requires `langgraph<1.2`, and `langgraph` 1.2.3 was itself yanked upstream for a merge
regression. The 3.x line is the one that supports langgraph 1.2.

What is actually pinned, and resolved: langgraph 1.2.11, langgraph-checkpoint-postgres
3.1.2, langchain-core 1.6.1, openai 2.54.0. `langgraph.prebuilt` is deprecated in this line
— use `StateGraph` and `langgraph.types.interrupt` / `Command` directly.

### Two scopes, not one: `agent:invoke` and `agent:review`

`agent:invoke` *starts* an agent. Machines hold it, because nearly every real run is
triggered by an event rather than by somebody clicking.

`agent:review` sees and answers what an agent is waiting on. It is held by DS_APPROVER,
DISTRICT_APPROVER, DMC_OPERATOR and DISPATCHER, and by **no machine role** — with
`allow_machine=False` on the dependency as belt and braces. An agent resuming its own
approval would make every human gate in the platform decorative.

The split was added after noticing that the approval inbox was readable only by ADMIN,
which would have left the dispatchers and approvers who actually answer these unable to
open the queue.

### `GET /agents/threads?status=interrupted` needs the graph, not the checkpoint table

The approval inbox returned `[]` while runs sat paused. The state field named
`interrupt_payload` is never written, because the pause is LangGraph's mechanism rather than
ours: only `graph.aget_state()` knows, via `snapshot.interrupts`.

So the endpoint lists thread ids from the checkpointer and then asks the graph about each.
**That is N+1 by construction.** Fine while live threads are few; a deployment with
thousands of pending approvals wants an index on the checkpoint table instead, and the first
cyclone is the wrong time to discover the inbox is O(threads). The comment is on the
function.

An inbox that is quietly empty is the worst failure a human-gate design can have: the gates
hold, and nobody can see what they are holding.

### Starting a run that is already in flight rejoins it

`runtime/run.py` exists for one reason. LangGraph takes fresh input on an interrupted thread
as a new update from `START`: the graph re-enters at the top, every pre-interrupt node runs
again, and the approval an officer is halfway through answering is rebuilt underneath them.

A retried webhook, a redelivered event and an impatient second click must all land on the
pending run and leave it alone. `start_run` checks `snapshot.next` and returns the pending
state untouched. A *finished* run does re-run — rejoining applies to work in flight, not
work that is over, or a subject could never be reprocessed after a fix.

Both the HTTP surface and the event consumers go through it, because two copies of this
logic would drift and the drift would show up as "it works when I click it".

### Events start agents through one declarative table

`consumers/triggers.py` maps event type → agent. One file, so the answer to "what happens
when a report arrives?" is not spread across six directories. Three fields per row have no
sensible default: where the subject id is, which payload fields the run may carry, and
whether the row is enabled.

`carry` is the one worth knowing about. A checkpoint outlives the run and goes to a trace
exporter that leaves the country (ADR-011), so an event payload copied wholesale into agent
state is how a phone number ends up in one. **A field not named in `carry` does not reach
the agent.**

The subscription declares `side_effect_free=False`. Agents draft alerts, propose dispatches
and flag disbursements; replaying a week of incident events into this consumer would re-run
every one of those, so the bus refuses to hand it a replay at all.

Every routing refusal — no subject, unknown agent, unroutable type — *acknowledges* the
event and logs loudly. A message that will never succeed being redelivered forever is a
poison pill that blocks everything queued behind it, and the outage it produces looks
nothing like its cause. Only a genuine transient failure propagates.

**The one row in the table today is disabled on purpose.** `noop` classifies with three
keywords and asks a person about everything else; pointed at live citizen reports it would
fill the approval inbox with questions no officer can usefully answer. File 15 replaces that
row with the intake agent. Flipping `enabled=True` is how you watch the wiring work.

### The eval harness scores the agent and the platform separately

`runtime/eval.py` reports two accuracies, and the gap between them is exactly what the human
gates are buying:

- **as delivered** — what came out, review included. The number a ministry cares about.
- **agent alone** — what the agent got right before anybody looked at it.

Calibration is scored on the second. Scoring a reviewed case as a hit for the model would
report every agent that routes to a human as *perfectly calibrated* — which would make ECE,
the number that justifies using `confidence` as a gate at all, meaningless in exactly the
direction nobody would notice. The first version of the harness did this, and the smoke set
scored ECE 0.31; correcting it gives 0.11.

The human-review rate is reported alongside how often review **changed** the outcome, because
both halves are needed to read a gate. Review that never changes anything is a queue burning
operator attention; review that changes everything means the agent routes well and is wrong
whenever it hesitates. Neither shows up in accuracy.

Thresholds live in `thresholds.json` beside the fixtures, not in the code: the bar for a
ten-case smoke set and a thousand-case regression set are not the same bar, and a gate
nobody can pass is a gate somebody deletes.

### Three bugs the tests found, all of them real

**ledger-svc and agent-svc never mounted `AuthenticationMiddleware`.** Both services'
`deps.py` carried a comment saying the principal is "set by AuthenticationMiddleware", and
neither app factory added it. ledger-svc's entire authenticated surface — 30 endpoints
including the disbursement human gate — returned 401 against a valid token. Domain and
schema tests cannot see this; only an HTTP-level test can.

**The checkpointer was handed a DSN psycopg cannot parse.** The service is configured with
one database URL and everything else reaches Postgres through SQLAlchemy, so it names a
driver: `postgresql+asyncpg://`. LangGraph's checkpointer is psycopg-based and reports
`missing "=" in connection info string` — which reads like a malformed password and sends
you looking in entirely the wrong place. `runtime.checkpoint.psycopg_dsn` strips the driver.
**Durable checkpoints could never have booted in a real deployment before this.**

**LangGraph's `add_node` rejected a `Callable` type alias.** A `Callable[[AgentState], ...]`
alias erases the parameter *name*, and LangGraph's own `_Node` Protocol names it `state`.
`runtime.nodes.Node` is a matching Protocol for that reason.

### Windows needs the Selector event loop, and the root `conftest.py` sets it

psycopg's async mode refuses to run on Windows' default Proactor loop, so every test that
boots agent-svc with durable checkpoints failed locally while passing in CI and in the
Docker image, both of which are Linux. A suite that fails only on the machines the team
actually types on is a suite people learn to ignore.

The root `conftest.py` selects `WindowsSelectorEventLoopPolicy` on win32 and is a no-op
everywhere else. The service itself now refuses to start with a sentence naming the cause
and the fix, rather than surfacing the driver's message — and it refuses rather than
degrading to an in-process saver, because losing every paused approval on the next restart
is not a fallback, it is a silent loss of the human gates.

---

## File 13 is done — the forecast agent, and the decisions inside it

The first real agent. It turns "150 mm of rain in Kandy district" into "these divisions lose
road access within 48 hours; this many of those households contain someone over 70".

```bash
uv run pytest tests/agents/forecast                                    # 81 tests
make eval AGENT=forecast                                               # -> artifacts/eval/
uv run python -m agent_svc.agents.forecast.replay --scenario ditwah --assert-lead-time 24
```

### The headline claim is a test, and it passes with 48 hours to spare

`LK-21 first reached impact class 3 48 hours before landfall.` Build file 13 says this must
be a test rather than a hope, so it is one: the replay feeds the committed Ditwah fixture
through the production nodes and asserts the lead time. No network, no database, no model
provider.

The second test beside it is the one that stops the first passing for the wrong reason. A
forecast putting every division in Sri Lanka at major impact three days out has technically
warned Kandy and has told nobody anything, so `test_the_forecast_does_not_flag_the_whole_
country` asserts that fewer than 80% of divisions ever produce a row.

### The dimensional error that would have looked exactly like a working early warning

The first version summed the observed 24-hour rainfall and the forecast, then compared the
total against NBRO's thresholds. **NBRO's thresholds are 24-hour figures.** A two-day total
measured against a one-day line crosses every evacuate level about a day early, produces a
plausible table, and from the outside is indistinguishable from an early warning system that
works.

`DivisionRainfall.peak()` now returns the worst *single* 24-hour accumulation in view and the
window it falls in — which is also where `lead_time_hours` comes from, so "class 3 within 48
hours" is a statement the number supports. Caught by doing the arithmetic against the Ditwah
curve by hand before building anything on top of it.

### Only NBRO's own evacuate line produces class 4

The modifiers — a fragile slope, a division that floods more often than annually — can lift a
division to major. They cannot lift it to severe. Class 4 is what an evacuation advisory is
written against, and moving families out of their homes has to rest on the published
threshold the country already agreed to, not on our judgement that a slope looked fragile.

`MODIFIER_CEILING` is that rule, and `test_a_modifier_cannot_reach_severe` is the guard.

### A model is used twice, and neither use decides anything

**`reconcile_sources`** writes the explanation when Met and NBRO disagree. It cannot lower
the hazard level: `apply_floor` takes the most severe source and is applied to the model's
output *after* the call, not requested in the prompt. A rule that lives only in a prompt is
one the model may decline to follow on the one input that matters, and a fluent paragraph
arguing Amber over NBRO's EVACUATE is exactly the failure mode. Over-warning costs a
preposition; under-warning costs the thing the platform exists to prevent.

The degraded path is the same function as the floor, so losing the provider changes the
rationale and never the level.

**`explain`** writes the trilingual narrative. Output containing a number that is not in the
drivers is discarded whole — not flagged, discarded — and the static template is published
instead. A fabricated figure here reaches a GN officer as a specific claim about their own
village, attributed to the government, at the hour they are deciding whether to move people.
The check is blunt and has false positives; a sentence is cheap.

A narrative missing Tamil is a failed generation, not two-thirds of a success.

### Confidence is about the inputs, and the fixture set proves it means something

A rule engine's thresholds either were or were not crossed; what varies is how much to trust
the number compared against them. So confidence falls with gauge outages and with a missing
NBRO survey.

The outage penalty is scaled by the **share** of nearby gauges that are silent, not the
count. At Ditwah's peak roughly a fifth of the national network is down; a per-station
penalty read that as forty separate failures and drove every division in the country to 0.37
confidence at the exact hour the forecast mattered most. Two silent gauges out of three
nearby is a real problem; six out of thirty is a Tuesday.

**The eval fixture set deliberately contains cases the engine cannot get right** — a gauge
blackout, an unsurveyed high-hazard division, a riverside division with no elevation input.
Without them the low-confidence bins are empty and ECE is vacuous. With them:

| Confidence | Cases | Stated | Actual |
|---|---|---|---|
| 0.2–0.3 | 2 | 0.25 | 0.00 |
| 0.7–0.8 | 3 | 0.70 | 0.67 |
| 0.8–0.9 | 13 | 0.85 | 0.92 |

ECE 0.086, against build file 13's requirement of 0.15. Accuracy is 77.8% and the bar is set
at 75% for this agent alone, because four of the eighteen cases are ones it is *designed* to
be wrong about — and deleting them to reach 90% would make the calibration number meaningless.
That is what per-agent thresholds in `thresholds.json` are for.

### Two schema contradictions, and the database won both

**`drivers` is a JSONB object, not a list.** `hazard.impact_forecast` has a CHECK requiring
`jsonb_typeof(drivers) = 'object'`; build file 13 describes `list[Driver]`.
`ImpactScore.drivers_as_object()` keys by factor name, which also enforces one entry per
factor — something a list cannot.

**`method` is `RULE_THRESHOLD`, not `RULE_THRESHOLD_v1`.** The CHECK allows `RULE_THRESHOLD`
and `MODEL` only, and `model_version` is a separate column. Same fact, split the way the
schema splits it.

Also: build file 13's trigger example reads `landslide_zone <= 2` for a high-hazard rule and
names the action `NOTIFY_DS_PREPOSITION`. NBRO zone 4 is the *very high* hazard zone, and
`TRIGGER_ACTIONS` has no such action — the equivalent is `PREPOSITION_REQUESTED`. Both are
documented at the top of `exposure.py` and `triggers.py`.

### Two attribute directions were decisions, not facts

`landslide_zone` higher-is-worse comes from NBRO. `road_access_class` had a range and no
stated direction anywhere in the schema or the seed, so it is fixed in `exposure.py` to match
— higher is worse throughout — because two adjacent columns counting in opposite directions is
a bug waiting in whichever one somebody reads second. `flood_return_period_m` is read as
months between floods, lower being worse.

### What the engine cannot see, and does not pretend to

Build file 13 lists elevation and distance to the nearest waterway among the inputs.
`admin.gn_division` carries neither. Deriving them from a centroid would produce a number
that looks like terrain data and is not, so they are absent — and the consequence is in the
eval set as `riverside-flood-no-slope-signal`, a case the engine gets wrong for a reason
that is written down.

### gov-mock was not reproducible, and its own docstrings said it was

Nine call sites across four modules seeded `random.Random` from `hash()` of a tuple
containing a string. **Python randomises string hashing per process**, so the same station at
the same simulated hour returned 67.9 mm, then 54.4 mm, then 48.6 mm in three consecutive
runs. Nothing raised. Every mock's docstring claims "the same simulated hour produces the
same reading on every machine and every replay"; none of them did.

`derive.seed_for()` fixes it with a SHA-256 digest — in the same module whose docstring
already warned that `hash()` is randomised per process. `tests/gov_mock/test_reproducibility.py`
runs each derivation in **subprocesses**, because within one interpreter `hash()` is perfectly
stable, which is exactly why 122 existing tests over these mocks never saw it.

The demo would have shown different weather on every boot, and the Ditwah replay would have
been unrepeatable.

### The eval harness needed two fixes to host a second agent

**Fixtures were globbed.** `load_cases` read every `*.jsonl` in the directory, so `make eval
AGENT=forecast` would have scored the forecast agent against `noop`'s labels and reported a
confident 0%. Now `{agent}.jsonl` wins when it exists.

**Thresholds were shared.** A deterministic three-keyword classifier and a threshold engine
whose fixture set deliberately includes cases it cannot see are not comparable, and one
accuracy bar across both would force somebody to delete the cases that make the calibration
honest. `thresholds.json` now takes an `agents` block.

**`AgentSpec.eval_build`** is the third piece. The forecast agent's production graph talks to
the Met Department, NBRO and core-api; a harness that had to stand all three up is a harness
nobody runs before pushing. The spec supplies a one-node graph over the scoring engine
instead — which is the part with a confidence worth calibrating — and says so in its own
docstring. The service never uses it.

### `GET /admin/gn-divisions/exposure` is new on core-api

Every division in the named districts, with the exposure attributes, in one call. The
per-division endpoint would be one round trip each, several hundred per generation, several
generations an hour. No geometry, ever.

---

## File 14 is done — the warning agent, and the decisions inside it

```
receive_forecast -> decide_alert_needed -> select_template -> resolve_targets
-> plan_channels -> validate -> [human_signoff] -> dispatch -> collect_receipts
-> assess_gaps -> record
```

Eleven nodes, one interrupt, and the first agent in the platform that is `gated=True`.

```bash
uv run pytest tests/agents/warning tests/alerting/test_sms_segments.py
make eval AGENT=warning
uv run python -m tools.sms_segment_check          # exits 0, tightest pass has +8 units
```

### The model does not write alert text, and three things enforce it

The constraint is the whole design, so it is worth writing down what actually holds it up
rather than that it is a rule.

Selection is a lookup over `RULE_MATRIX` in `agents/warning/catalogue.py`, keyed on
`(hazard_type, impact_class)`. A model is consulted **only when two or more published
templates sit at or above the matrix's answer** in CAP severity order — otherwise a token
would be spent choosing between one option. Its answer is then checked, not trusted:

- not a published code for this hazard → discarded, matrix answer used;
- below the severity floor → discarded, and logged at `error`;
- provider unreachable or slow → discarded, matrix answer used.

Parameter values are a separate refusal. `validate_parameters()` accepts a proposed value
only if it appears character for character among the structured facts. A model may say
which known value fits; it may not supply one. `shelter_name` filled with "the temple on
the hill" is free text with a template around it, and free text is precisely what the soft
gate exists to catch.

### An unfillable template asks a person; it never falls back to a weaker one

The sharpest decision in the file. Class 4 flood selects `FLOOD_EVACUATE_IMMEDIATE`, which
needs `shelter_name`. If no shelter has been named, the run raises `NoSuitableTemplate` and
interrupts.

It does **not** select `FLOOD_WARNING`. A downgraded evacuation order goes out, reads as
deliberate, and tells people to prepare when they were meant to leave — a silent failure
with nothing in the record to show it happened.

There is no safety-location registry wired yet, so `shelter_name` arrives with the run
(`SUPPLIED_FACTS` in `graph.py`) from the operator or trigger that started it. That is why
a bare class 4 run correctly pauses: the agent genuinely does not know where to send
anybody. Wiring the registry is a port and an endpoint and changes no rule here.

### One class band per run, and the band is in the subject

`warning:hazard_event:{event}#c4`. A run alerts on **one** impact class and targets only
the divisions at that class.

Mixing bands forces a choice between two harms: the class 4 text to everybody tells a
watch-level division to evacuate; the class 2 text tells a division in severe trouble to
monitor water levels. Divisions at other bands are named in the output as `deferred_bands`
and need their own run.

`#c4` rather than a second colon because the resume endpoint splits a thread id on the
first two colons only — a colon would survive, but a subject that looks like it has
structure the splitter understands is one somebody eventually splits wrongly. There is a
test.

### Two dispatch tools, and only one is gated

`dispatch_templated_warning` is ungated. `dispatch_free_text_warning` is
`requires_human_gate=True`, so `runtime.tools.assert_human_gate` refuses it without a
decision naming *this* subject. Three independent layers hold the gate:

1. the tool registry refuses the call;
2. `validate` will not mark a free-text alert dispatchable, so routing reaches
   `human_signoff` first;
3. alerting-svc refuses an alert whose `requires_human_signoff` is set and `signed_off_by`
   is null.

A gate over the *template* path would mean a fully reviewed evacuation order waits for
somebody to be awake, which is why there are two tools rather than one with a flag.

### A sign-off flips `dispatchable`; it does not re-run `validate`

Re-running validation after an approval would mint a second CAP identifier for one alert
and set the same signoff flag again. So `human_signoff`, below the interrupt, sets
`requires_signoff=False, dispatchable=True` — **only when `validate` found no problems**. A
person approves text; they do not approve a schema violation or an over-cap fan-out.

An operator answering `no_suitable_template` with a template code routes back through
`select_template`, which honours their choice over the matrix (`select_named`, provenance
`HUMAN`) — at most once, guarded by `operator_chose_template`. An approval inbox that
re-asks the same question is one people stop opening.

### An approval is not a channel for new copy

An operator's resume may approve, refuse, or name a template. It may **not** author free
text. `validate` has already built and checked the CAP document by the time the interrupt
fires, so text arriving in the decision would reach a district having passed no trilingual
check, no CAP validation and no segment measurement. `human_signoff` logs it at `error` and
drops it.

The operator's route for something the templates do not cover already exists and is file
09's: `POST /api/v1/alerts` with `free_text` lands in `PENDING_SIGNOFF`, where the text is
validated before anybody signs it. There is a test.

### Targets are not in the checkpoint

A national fan-out is several hundred thousand households and a checkpoint row stays under
64KB. What travels is division codes and per-division counts.

The cost is that a run reads the directory **three times** — `resolve_targets`, `dispatch`
and `assess_gaps` — rather than once. That is the trade against a resume that would load
half a megabyte of contact hashes before it could ask a person a question, and against a
checkpoint table growing by the population of every warned district. The third read is
removable: `assess_gaps` only needs denominators and `target_counts` already holds them,
but it would mean `gaps.assess` taking counts instead of targets, which is the shape its
unit tests are written against. Worth doing before a real national fan-out; not worth doing
blind.

### `reachability_confidence` is about the picture, not the delivery

Not "how likely is it these people got the message" but **how much of this division's
outcome we actually know** — the share of targets with a definite result either way,
reduced for every channel that failed outright.

A division where every receipt came back UNKNOWN scores `MIN_CONFIDENCE` even if everybody
got it, because the honest statement is that we cannot tell. A confident 40% confirmed is a
division to send a vehicle to; an unconfident 90% is a division to send a vehicle to *and*
fix the receipts on.

### Quiet hours are Colombo local, and the bypass is the point

22:00–05:00, SMS/USSD/PUSH only, released at 06:00. Applied in Colombo local time because
the rule is about when somebody is asleep and Sri Lanka is UTC+5:30 — in UTC it would
silence the wrong five and a half hours, which during an overnight landfall is exactly the
wrong ones.

`impact_class >= 3` bypasses it entirely. The exception is what makes the restriction safe
to have: a rule that silenced everything at night is one somebody removes the first time it
matters.

The clock is injected (`build(..., now=)`), not read inside a node — a rule about what the
agent does at a particular hour cannot be tested by a test that cannot fix the hour.

### CAP moved to `sarana_shared.domain.cap`

`validate` builds and validates the CAP document **before** handing it to alerting-svc, so
a problem is caught while the graph can still route it to an operator. That needed the CAP
module somewhere both services reach, so it moved out of alerting-svc;
`alerting_svc.domain.cap` re-exports it and every file 09 call site is unchanged. Two CAP
validators disagreeing about whether a warning is dispatchable is not a disagreement
anybody finds until it matters.

`cap_case()` came along with it, replacing alerting-svc's private `_cap_case` — the copy
that would have rendered `STORM_SURGE` as `Storm_surge` in whichever service was written
second.

### An oversized SMS body is recorded, not refused

`sarana_shared.domain.sms` counts segments in UTF-16 code units. Sinhala and Tamil are
UCS-2, so two segments is 134 units against English's 306.

`tools/sms_segment_check.py` is the CI gate over the **seed**, with worst-case parameter
values taken from the longest names in `data/seed/reference`. All twelve templates pass;
the tightest is `FLOOD_EVACUATE_IMMEDIATE` in Tamil at +8 units.

At *dispatch* time an oversized body is logged and carried on `validation.oversized_sms`,
not blocked. Refusing to send a warning because a long division name pushed it three
characters over would trade a real warning for a tidy one.

Build file 14's DoD names `data/seed/alert_templates.yaml`. This repository seeds templates
as JSON at `data/seed/reference/alert_template.json` and has no YAML in the seed at all;
the checker defaults to the file that exists and takes a path argument.

### The eval calibrates nothing, and says so

`make eval AGENT=warning` scores template selection: 15 cases, 100% accuracy, ECE 0.099.

The ECE is reported and is **not** the gate — accuracy is. Selection is a lookup, so it is
right by construction whenever the catalogue has the template, and the stated confidence is
nearly constant. The 0.099 is systematic under-confidence over a rule table, which is the
honest shape. Manufacturing a spread of confidences so the reliability diagram had an
interesting diagonal would produce a number that looks like a calibrated safety property
and is not one.

That is the opposite shape to the forecast agent's thresholds, and `thresholds.json` now
says why for both.

### agent-svc is now the second credential holding `household:contact_read`

Worth flagging on its own, because it widens a blast radius that file 09 had deliberately
kept to one service. The warning agent needs per-household targeting to do what file 14
specifies — deduplicate two households sharing a handset, route language per household,
count the households with no channel at all — and each of those is the difference between
a delivery figure that is real and one that is decorative.

The alternative was an endpoint on alerting-svc that resolves targets on the agent's
behalf, keeping the scope in one place. That is the better shape and it is more work than
file 14 asks for; it is written down here so the next person choosing between them is
choosing rather than inheriting.

`alert:dispatch` on a machine is not the same kind of question: the soft gate for an alert
lives in `requires_human_signoff` and in the gated tool, not in the token, and the two
scopes a machine genuinely may never hold — `dispatch:commit` and `disbursement:release` —
are still stripped at mint time by `strip_human_gates`.

### Still placeholder, and honest about it

- **`NullHistory` is wired, so nothing is suppressed for fatigue in a running stack.** The
  rule, the window and both directions of the escalation test are real and tested; what
  does not exist is a query over `alerting.alert` per household. The adapter logs a warning
  on every call, because the failure mode — the same watch-level message every fifteen
  minutes for three days — looks like the platform working hard rather than broken.
- **`AlertingDispatcher.receipts` expands `/delivery`'s aggregate counts into synthetic
  per-target receipts.** That endpoint groups by channel and status and does not list
  targets, so per-division arithmetic in a live stack is currently right in aggregate and
  not attributable per household. A `GET /alerts/{id}/receipts` on alerting-svc closes it;
  the port already has the right shape.
- **`_dominant_languages` reads a `language_pct` field core-api does not yet return**, so
  in a live stack every division falls back to the default language order. Household
  `preferred_language` — which routes most messages — is real and comes from
  `admin.household`.
- **The warning agent has never run against the live stack.** The same position file 13 was
  in: the ports, the graph and the eval all work against fakes, and `main._build_warning`
  is reviewed rather than exercised.
- **No event starts it.** `consumers/triggers.py` has no row for `warning`. A forecast
  generating a class 4 does not currently start a warning run. It is one row, deliberately
  not added until somebody has run the agent by hand against a booted stack once —
  pointing it at live forecasts before that would fan out to real targets on the first
  generation.

---

## File 15 is done — the intake agent, and the decisions inside it

```
receive_report -> transcribe -> detect_language -> translate -> extract -> geolocate
-> plausibility -> embed_and_dedup -> [human_review] -> link_or_create -> record
```

Eleven nodes, one interrupt, `gated=True`.

```bash
uv run pytest tests/agents/intake
make eval AGENT=intake
uv run python -m agent_svc.agents.intake.bench --reports 200 --assert-p95 45
```

During Ditwah, FloodSupport volunteers phoned each request to verify it, for 300,000+
people. This agent is the replacement for that phone call, and almost everything in it is a
refusal to do something a volunteer would not have done.

### Four refusals, and each has a test named after it

**It never invents a people count.** `people_at_risk` is 40% of the deterministic triage
score, so a number the agent produces decides who a crew reaches first. Every count carries
`people_at_risk_basis` — the span of source text that justified it — and
`extraction.enforce_basis` strips any count whose basis is not genuinely a substring of the
source. Stripped, not corrected, not re-asked: a number whose evidence turned out not to
exist is not worth keeping. A basis that is more than 90% of the report also fails, because
quoting everything justifies nothing.

**It never invents a coordinate.** There is no port through which a model can return a
latitude and longitude. Geocoding is a gazetteer lookup. An ambiguous landmark — two matches
in different divisions, which is the normal case in Sri Lanka — produces a GN division and
**no point at all**. A division is a village-sized area and is dispatchable; a pin picked
from three equally good matches is a guess wearing a coordinate's clothes.

**It never quietly merges two households' reports.** See below.

**It never rejects a report.** `plausibility.py` produces flags, and a flag routes to a
person. The cost of ignoring a real report because it looked implausible is a death; the
cost of a human spending twenty seconds on a false one is twenty seconds.

### Dedup under-merges on purpose, and every failure lands on "separate"

A duplicate incident costs a dispatcher ten seconds. A false merge means a household
reported, was folded into another family's incident, one team went to that address, and the
family who reported waited for someone who never came — and nobody noticed, because the
queue looked short.

So: auto-link at ≥0.90 cosine, separate below 0.72, and the band between goes to a model
that must be **confident and say yes** (`MERGE_CONFIDENCE = 0.85`, deliberately above the
platform's 0.70 review threshold). Every other outcome — a low-confidence yes, an
unavailable provider, an unparseable answer, a confident no — produces two incidents and a
flagged pair. There is a test for each of those four.

`DedupStats` reports the duplicate rate and the false-merge rate **together**, because a
duplicate rate alone always improves by merging harder, which is the behaviour that must
not be rewarded.

### Language detection is a Unicode script test, not a model call

Sinhala is U+0D80–U+0DFF and Tamil is U+0B80–U+0BFF, disjoint from each other and from
Latin. So `lexicon.detect` is a character-range count: exact, instant, free, and impossible
to get wrong the way a classifier gets things wrong. It returns a **mix** rather than a
winner, so code-switching is a first-class answer — it is normal here, it is the hardest
input the platform receives, and it is what upgrades the model tier.

Digits and punctuation vote for nothing. Without that, `0771234567` reads as confidently
English and routes to an English reviewer.

### Two real bugs the fixtures caught in the lexicon

Worth recording because both were invisible until the eval ran.

**Generic water words sat in two categories.** `நீர்` (water) was in FLOOD and `தண்ணீர்`
(drinking water) in SUPPLIES_NEEDED — and the first is a *substring* of the second, so a
Tamil flood report matched the supplies list and was typed as a request for a bottle. Fixed
by removing every bare word for "water" from both lists. Substring matching over a short
list only works when the terms are specific; the generic ones are exactly what breaks it.

**One Tamil term had a Sinhala first character.** `"වெள்ளம்"` — `ව` followed by Tamil — so
it could never match anything. Mixed-script typos in a trilingual table are invisible on
screen and silent at runtime.

Both are arguments for the module's own instruction that a native speaker should review any
addition to that table.

### The agent writes no incident summary at all

`incident.incident.summary` is a localised JSONB column requiring all three languages. The
agent has a report in one language and no reviewed translation, so the only summaries it
could write are model prose nobody checked, or one language copied into three fields and
labelled as three. The first is unreviewed text about somebody's emergency; the second is a
lie about what the record contains.

So the column stays null — the same choice `incident_svc.service.intake` already made — and
the incident is identified by its type and division, which the console renders trilingually
from the taxonomy. `SUMMARY_NOT_WRITTEN` is a named constant so nobody "fixes" it by
accident.

### The eval scores the degraded path, and its ECE is meant to be bad

94.1% accuracy over 17 cases, ECE 0.532 against a 0.60 gate. Both numbers need explaining
and `thresholds.json` carries the long version.

The set deliberately includes reports a keyword list **cannot** resolve — a flooded road to
a hospital is both an infrastructure failure and a flood — because an eval containing only
the cases the lexicon handles would report a degraded path as though it were the real one.

The ECE is high because the deterministic path states a **fixed** 0.45, chosen to sit below
the 0.70 review threshold so every keyword extraction is confirmed by a person. It is a
policy constant, not a belief, so it does not track how often the path is right — and here
it is right 93% of the time. The only way to "fix" the number would be to raise the constant
above the review threshold, which would start auto-publishing keyword guesses into
life-safety decisions. Accuracy is the gate; ECE is reported and not relied on.

### The bench measures the floor, not the budget

`bench.py --reports 200 --assert-p95 45` runs 200 reports concurrently through the real
graph against in-process fakes: **p95 629 ms**, three orders of magnitude inside build file
15's 45-second budget.

That figure is the latency *the platform adds*. It excludes the ASR, translation and
embedding providers, and transcription alone is 5–25 s of the real budget. Simulating that
with a sleep would produce a number that says whatever the sleep says, so the fakes return
instantly and the docstring says what the number is. `--audio-share` and `--asr-latency`
exist for anyone who does want to model the whole budget, off by default.

A run that fails this gate is definitely too slow. A run that passes is not thereby proven
to meet 45 s in production.

### Still placeholder, and honest about it

- **No per-language WER, and none can be produced yet.** Build file 15 asks the eval to
  report it, and doing so needs a held-out set of real Sinhala and Tamil audio with human
  transcripts. Generating audio to measure ASR against would measure the generator. The
  build file is right that a blended WER hiding a bad Tamil result is worse than none — and
  a WER printed from fixtures nobody recorded is exactly that. It is absent rather than
  fabricated.
- **No adapters, so the agent is not wired into the service.** `main.py` has no
  `_build_intake`: there is no `Transcriber` implementation, no `Embedder`, no gazetteer
  client, and no `ReportStore` over `incident.raw_report`. The ports and the graph are
  complete and every one of them is exercised against fakes; what does not exist is the
  layer between them and Postgres. This is a bigger gap than file 14's — the warning agent
  at least has adapters that are merely unexercised.
- **The gazetteer does not exist.** `geolocate` needs place-name lookup and core-api has no
  such endpoint. Sri Lanka's GN division names are in `data/seed/reference/gn_division.json`
  and would serve as a first gazetteer; landmarks below division level would need a real
  source.
- **Still nothing starts an agent from an event.** `consumers/triggers.py` has one row, for
  `noop`, still disabled. File 15 was supposed to replace it with the intake row — and that
  row should not be turned on until the adapters above exist, because a trigger pointing at
  live citizen reports with a refusing store would fail on every report of the day.
- **Dedup recall is untested against a real pgvector index.** The two-stage design, the
  bands and every adjudication path are tested; what is not is that an ivfflat cosine search
  over `report_embedding` actually returns a Tamil voice note when queried with a Sinhala
  SMS. That needs the embedder and a live index, and it is the assumption the whole recall
  stage rests on.

---

## File 16 is done — the triage agent, and the gate it exists to stop at

```
receive -> score_priority -> rank_queue -> check_resources -> compute_routes
-> assemble_plan -> dispatch_signoff  ** MANDATORY HUMAN GATE **
-> approve: release -> record       |  reject: record_rejection -> record
```

```bash
uv run pytest tests/agents/triage
uv run pytest tests/agents/triage/test_gate_cannot_be_bypassed.py
make eval AGENT=triage
```

This is the agent the dispatch gate has been waiting for since file 12. `NullResumer` can
now be replaced — see the gap list at the end for what that still needs.

### The gate holds at four independent layers, and each is tested on its own terms

`test_gate_cannot_be_bypassed.py` is the most important file in the agent, and it asserts
each layer separately rather than through the others — four layers that could only be
tested through each other would be one layer wearing four hats.

1. **The graph.** A plan pauses at `dispatch_signoff` and stays paused. Re-invoking without
   a decision does not advance it.
2. **The tool registry.** `release_dispatch_plan` is `requires_human_gate=True`, and
   refuses on no decision, a decision naming a different plan, and a recorded refusal.
3. **The scope model.** `Scope.DISPATCH_COMMIT` is in `HUMAN_GATE_SCOPES` and absent from
   `ROLE_SCOPES[Role.AGENT]`; `strip_human_gates` removes it from any grant set, asserted
   against the function rather than only against the AGENT role.
4. **The gate function.** `dispatch_gate.assert_step_up` refuses a missing and a stale
   second factor; `assert_undecided` refuses a plan that already carries one.

The database trigger is the fifth and lives in `tests/schema`, where Postgres is available.

**The strongest form of the guarantee is structural, not behavioural.** `PlanStore` exposes
exactly `propose` and `record_rejection` — there is no method on any port through which this
agent could release anything. A test asserts that the port has those two methods and nothing
else, so adding a third is a deliberate act somebody has to argue for.

### The score is a published formula and the LLM cannot touch it

Six weighted terms, all shown to the dispatcher: immediate danger (heaviest at 0.28),
people at risk, vulnerability, incident type, age, corroboration. They sum to 1.0 so the
score reads as a fraction, and `factor_breakdown()` returns every term, every weight and
every contribution for every incident.

**A first pass had `people_at_risk` heavier than `immediate_danger`** and the test caught
it. Build file 16 says immediate danger is the heaviest weight; it now is, and the test
asserts it against `max()` rather than a hardcoded number so the property survives a
retune.

The model writes one trilingual sentence *after* the ranking and the routes are fixed. It
is discarded whole if it comes back in fewer than three languages. A test runs the same
queue with and without a model and asserts the ranking and the route summary are identical —
which is build file 16's "a total model outage is close to a non-event", made checkable.

### Ageing, and the failure in the other direction

An incident that sits unrescued rises, or a queue sorted on severity starves every moderate
incident for the whole event. The curve is linear to two hours — the same
`AGE_SATURATION_MINUTES` file 08 uses — and **flat after it**.

Flat matters as much as rising. An unbounded age term eventually lets a four-hour-old supply
request outrank a fresh medical call, which is the opposite failure and harder to notice
because the queue still looks busy. Both directions have a test.

### Location confidence reduces dispatchability, never urgency

Build file 16 is precise about this and it is worth preserving in the summary: a report
nobody can place is exactly as urgent as one with a GPS fix — somebody is still in the
water. So `score` and `dispatchability` are separate outputs, the queue is ordered on
urgency, and the plan is built from what can be reached. An unplaceable incident stays top
of the queue and comes back as `unservable`.

Folding the two would quietly deprioritise the people whose reports the platform serves
worst, which is the population it exists for.

### OR-Tools is now a dependency, and there is still no road network

`uv add ortools` in `services/agent-svc`. It brings numpy, pandas and protobuf, and it
**downgraded protobuf from 7.36.0 to 6.33.6** — the full suite passes on that, but it is
worth knowing if something protobuf-shaped breaks later.

The solver is a real CVRPTW: per-vehicle transit callbacks, capacity as a dimension,
`VehicleVar(...).SetValues([-1, *allowed])` to bar a vehicle from an incident it cannot
physically reach, and a disjunction so one unreachable incident does not make the whole
problem infeasible. `SetAllowedVehiclesForIndex` does not accept a Python list in this
binding; the VehicleVar form is the one that works and it is a hard constraint rather than
a penalty, which is what the design wanted anyway.

**`travel times over a road network with flood-blocked edges removed` is not what this
does.** There is no road network in this repository — no OSM extract, no routing graph, no
edges to remove. Travel time is straight-line distance at a mode-dependent speed with a 1.4
detour factor, and "flood-blocked edges removed" is implemented as the thing the platform
actually knows: a division with `road_access_lost` is reachable by `NAVY`, `COAST_GUARD` or
`MILITARY` and by nothing else.

That gets the decision that matters right — who can reach a cut-off village — and it
under-estimates every ETA, because roads bend. Every ETA is a floor. Wiring a real routing
engine changes `routing.TravelModel` and nothing else.

### The responder vocabulary was guessed wrong and the test caught it

The first draft had `SAR_TEAM`, `BOAT`, `HELICOPTER` and `ARMY`. `incident.responder.type`
has none of them — the real list is `AMBULANCE, FIRE, POLICE, MILITARY, NAVY, COAST_GUARD,
VOLUNTEER, NGO, MEDICAL_TEAM, ENGINEERING`. So there is **no aircraft in the roster**, which
is why the travel model has no straight-line exemption: exempting one would model a
capability the platform does not have.

### Rejections are recorded as data, not as an error path

A rejection is a dispatcher telling us the ranking was wrong in a situation where they know
something the platform does not — the road is passable because they drove it, the family
already walked out, that address is a shop. None of that is in any database.

So `rejections.py` records a taxonomy reason imported from
`dispatch_gate.RejectionReason` (not restated — two lists that were meant to match are two
that eventually do not), appends **one observation per incident** rather than one per plan,
and re-queues. An unrecognised reason is stored as `OTHER` with the original preserved in
the note rather than refused: the dispatcher has already decided, and protecting a
vocabulary at the cost of the signal would be the wrong trade.

`distribution()` is the number that matters. An accept rate says how often the agent is
agreed with; the distribution says *how it is wrong*, which is what a change can be aimed
at.

### The eval measures rank correlation, and its fixtures are honest about what they are

100% accuracy, ECE 0.010 over ten cases. Both numbers need a caveat and `thresholds.json`
carries the long version.

Each case is a **whole queue** with an ordering, scored on Spearman correlation mapped onto
[0, 1] — build file 16 is explicit that agreement must not be measured as binary
agree/disagree, because a dispatcher who works the queue in a slightly different order has
not disagreed with it.

The ECE is near zero because the stated confidence **is** the measured agreement: the
formula is deterministic and has no separate belief about its own ordering, so inventing one
to fill the field would have been the dishonest option. It is self-calibrating by
construction and is not evidence of anything.

**The dispatcher orderings are agreed expectations, not recorded shifts.** No labelled
corpus of real dispatcher decisions exists. This is a regression gate on the formula, and
the proposal's ≥85% agreement target is validated during the pilot — the number must not be
quoted as though it had been.

### Still placeholder, and honest about it

- **No adapters, so the agent is not wired into the service.** `main.py` has no
  `_build_triage`: there is no `IncidentSource`, `ResponderSource` or `PlanStore` over
  incident-svc. The graph and all four ports are complete and exercised against fakes. Same
  position as file 15, and the same fix — an HTTP client per port.
- **`NullResumer` is still what incident-svc uses.** The agent now exists to be resumed, and
  the wiring — pointing `dispatch_gate`'s `ThreadResumer` at agent-svc's resume endpoint —
  has not been done. Until it is, `graph_resumed: false` is still what the approve response
  reports, which is honest and is not the finished state.
- **The restart test proves half of what its name says.** It compiles a *new graph object*
  over a shared in-process checkpointer, which proves the thread id is derivable and the
  checkpoint carries everything the resume needs — none of it lives in the closures. It does
  **not** prove Postgres round-trips the checkpoint; that needs the durable saver and a
  container restart, and the two halves have never been run end to end. The file says so in
  its own docstring.
- **No event starts it.** Consistent with files 14 and 15: `consumers/triggers.py` still has
  one disabled row for `noop`.
- **The rank-correlation target is unvalidated.** See above. It needs real dispatcher
  decisions, which is file 28 plus a pilot.

---

## The dispatch gate now resumes a real graph, and forwards a human's token to do it

`incident_svc.adapters.agent_runtime.AgentThreadResumer` replaces `NullResumer`. It closes
the seam file 08 opened, file 12 could not fill, and file 16 finally gave something to
resume.

### It forwards the dispatcher's own token, and that is not a shortcut

agent-svc's resume endpoint is `require(Scope.AGENT_REVIEW, allow_machine=False)`. **No
machine principal in the platform holds `agent:review`** — not `Role.AGENT`, not
`Role.SERVICE` — because answering an agent's question is a human act. incident-svc
therefore *cannot* resume the thread with a service credential, and the design does not try
to.

So `_caller_token(request)` lifts the bearer token off the approving request and passes it
through `dispatch_gate.approve` to the resumer. `Role.DISPATCHER` and `Role.DMC_OPERATOR`
both hold `agent:review`, so it works, and agent-svc records the decision against the person
who made it.

That is the truthful attribution as well as the only one that authenticates. A service
credential would have produced an audit trail saying incident-svc answered the agent's
question, which is false — and it would have routed around `allow_machine=False`, which is
the whole reason that flag is set. `resume()` refuses outright when no token is available
rather than falling back to anything.

Forwarding a token deserves care, so: it goes to one URL configured at boot, over one
endpoint, and it is never logged or stored.

### Two vocabularies meet, and the adapter translates

The gate says `decision: approve|reject` because that is what `dispatch_plan` records.
agent-svc says `approved: bool` because that is what every interrupt asks. `_as_resume_request`
converts, passes the rejection reason through, identifies the approver by id rather than
name — the decision lands in a checkpoint, and a checkpoint carries ids — and forwards
anything else the decision carried, so a dispatcher who trims a responder count while
approving does not lose it.

### Off by default, deliberately

`SARANA_INCIDENT_RESUME_AGENT_THREADS` defaults to false. A deployment running without the
agents has plans with no `langgraph_thread_id`, and the gate skips the resume for those
anyway — but a deployment with *some* agent-made plans and an unreachable agent-svc would
fail every approval on them, because `approve` treats a failed resume as fatal. That is
worse than reporting `graph_resumed: false`. Turn it on when agent-svc is reachable.

The asymmetry between approve and reject is unchanged and still deliberate: a failed resume
on approve stops the release, and on reject it is swallowed, because a rejection that cannot
reach the graph is still a rejection and leaving a declined plan in the queue looking live
would be worse.

---

## File 17 is done — the anomaly agent, and the boundaries that make it allowable

```
receive_batch -> aggregate -> normalise_by_exposure -> detect_anomalies
-> contextualise -> suppress_explained -> raise_flags -> record
```

```bash
uv run pytest tests/agents/ledger_anomaly
uv run pytest tests/agents/ledger_anomaly/test_exposure_normalisation.py
uv run pytest tests/agents/ledger_anomaly/test_no_individual_named.py
make eval AGENT=ledger_anomaly
```

**Read ADR-009 before touching this package.** It is the agent with the highest potential to
do harm and the harm is not technical.

### The one test that proves the design works

`test_a_severe_division_with_high_value_assessments_produces_no_flag`, paired with
`test_the_identical_profile_at_low_impact_does_produce_a_flag`. The same assessment profile —
40 assessments, 70% total loss, 90-minute approvals — at impact class 4 and impact class 1.
The first raises nothing; the second raises a flag.

That pair is the whole argument. A division that was genuinely hit hardest produces
assessments that are higher, more numerous and faster. Against a national or district
average, the worst-hit division in the country is the most anomalous division in the country
— and the officer who assessed the worst damage is the one most likely to be flagged for it.

So nothing compares a division to its peers. `normalisation.expectation_for` derives what
each division should produce from **its own impact forecast**, and every detector scores the
gap against that.

### An unsurveyed division is suppressed, which makes the agent blind in unwarned districts

That is the correct trade and it is deliberate. The tempting fallback — compare it against
the district mean instead — is exactly the peer comparison the module exists to avoid. A
detector that says nothing is recoverable; one that flags an officer for having been in the
wrong village is not.

Same reasoning for a division with fewer than eight assessments: ratios that swing on a
single row are noise a reviewer pays for.

### Officer identity is not a feature, enforced by absence rather than discipline

`Assessment` carries no `assessor_id`, no `approver_id`, no `user_id`. There is no port
through which one could be fetched, and a test asserts the dataclass has no such field.

That is stronger than a rule. A rule can be forgotten by whoever adds the ninth detector; a
field that does not exist cannot be grouped by. **The proxy is the trap** — "assessments per
assessor" is officer identity wearing a statistic's clothes — so the unit of analysis is
fixed to the GN division in `build_profiles`, in one place, with the reasoning attached.

### `confirmation_gap` joins coverage before it compares

The most valuable detector and the most easily misread. A division at 40% confirmation and
35% cell coverage is a **coverage problem**; firing on it would flag the least-connected
divisions in the country for being least connected, which is both wrong and backwards.

Unknown coverage suppresses too: an unknown is not a green light.

### Three layers stop a model naming anybody

1. **It is never told.** The prompt carries division facts only — no assessor, no approver,
   no household id. A model cannot name somebody it was never given. A test asserts those
   strings are absent from the prompt.
2. **It is instructed.** The prompt states the rules.
3. **Its output is checked.** `redaction.check` walks every string at any depth for ids,
   name-shaped pairs, a shipped deny-list of accusatory stems, and the *grammatical shapes*
   that make a finding without using any of the words — "this is clearly evidence of
   deliberate manipulation" contains no denied word and is rejected.

A rejected document is discarded **whole** and the flag falls back to the template block. Not
repaired, not re-asked: an output that reached for an accusation once is not one to negotiate
with.

The allow-list matters as much as the deny-list. Without `NOT_A_NAME` the check would reject
"Kandy District" and "Grama Niladhari", the contextualiser could never produce a usable
sentence, and a safeguard that blocks everything gets removed.

### An empty `innocent_explanations` suppresses the flag

Build file 17 inverts the usual shape of a safeguard here and it is worth preserving. An
empty list does not mean the pattern is damning — it means the context is too thin for a fair
review, and a reviewer handed nothing to rule out **supplies their own explanation, which
will be about a person**.

So the flag is withdrawn. The degraded path can still satisfy the rule because the template
context draws its explanations from the detector's own ruled-out list rather than from a
model.

### The eval prints both rates, and the harness gained a hook to let it

ADR-009 makes the false-positive rate first-class, so `AgentSpec` now carries an optional
`eval_sections` callable and `runtime/eval.py` renders it. Generic — any agent whose quality
is not captured by accuracy and calibration can add its own metrics — and it fails soft: a
broken addendum becomes a note in the report rather than an exception that discards it.

The anomaly report prints per-detector detection and false-positive counts side by side.
Currently 0 false positives across 8 clean divisions, 0 missed across 4.

Two thirds of the fixture set are divisions that must **not** be flagged. That ratio is the
point: any detector reaches 100% detection by flagging everything.

### Still placeholder, and honest about it

- **No adapters.** No `AssessmentSource`, `ExposureSource` or `FlagStore` over ledger-svc, so
  `main.py` does not wire it. Consistent with files 15 and 16.
- **`geo_implausible` uses a centroid, not the division boundary.** `admin.gn_division` has
  geometry and this agent has no port to read it, so the check compares each assessment
  against the cluster centroid. The evidence says so in the flag, because a reviewer should
  not be misled about the precision of the check. A point-in-polygon test is a port and an
  endpoint away.
- **`evidence_reuse` takes perceptual hashes as given.** Nothing here computes one; file 08's
  media handling would have to produce them, and its EXIF and hashing work is itself listed
  as incomplete above.
- **The disposition loop is not closed.** `FlagStore.disposition_rates` exists and nothing
  calls it: measuring the real false-positive rate needs dispositioned flags, which needs the
  console surface from file 20. The eval measures it against fixtures, which is a regression
  gate rather than a field measurement, and ADR-009's requirement to *publish* the rate is
  not met until that loop closes.
- **`category_drift` never fires in the seed.** It needs `permanent_housing_pct`, which
  `admin.gn_division` does not carry. It suppresses itself rather than guessing.

---

## File 18 is done — the supervisor, and the line that makes the gates real

```
receive_event -> check_sequencing -> detect_conflict
  -> [conflict] -> escalate_conflict -> human_review -> record
  -> [gate]     -> present_gate -> verify -> commit -> record
  -> [ordinary] -> dispatch_agents -> record
```

```bash
uv run pytest tests/agents/supervisor
uv run pytest tests/agents/supervisor/test_gates_three_layers.py
uv run pytest tests/e2e/test_full_correlation_chain.py
uv run pytest tests/agents/supervisor/test_resume_all.py
make eval AGENT=supervisor
```

**All six agents now exist.** Build file 18 says this is where the platform's safety story is
either real or theatre, and the difference turned out to be one function call.

### The resume payload is client input

`gates.verify_approval_record` goes back to the **database** and checks that a real approval
row exists — for this exact subject, by the person the payload names, with a second factor
verified inside the window. The payload is used to *find* the record and never as the record.

A graph that read `decision["approved"]` and committed would have authenticated a JSON field
written by whoever called the endpoint. `test_a_resume_claiming_an_approval_that_does_not_exist_is_refused`
is the single most important test in the agent, and there is a companion asserting the
database is read **on the happy path too** — without it, a short-circuit for "obviously fine"
payloads would pass every refusal test in the file.

Five distinct refusals, each with its own type so the message says which: no record, a record
for another subject, a record naming another approver, a stale second factor, a recorded "no".

### Three layers, tested with the other two out of the picture

Build file 18 asks for exactly this, and the reason is that three layers testable only
through each other are one layer wearing three hats — if the API check is what refuses in
every test, the database trigger could have been dropped two migrations ago.

1. **Graph** — the interrupt, the re-verification, the gated tool. Every test runs against a
   fake store with no HTTP and no Postgres anywhere near it.
2. **Scope** — both gate scopes are in `HUMAN_GATE_SCOPES`, absent from `ROLE_SCOPES[AGENT]`,
   and `strip_human_gates` removes them from *any* grant set, asserted against the function
   rather than only against the AGENT role.
3. **Database** — `tests/schema` asserts the trigger behaves; this file asserts the columns
   are still **declared**, so a migration that dropped `signed_off_by` or made `released_by`
   nullable fails a test that runs on a laptop with no Docker.

There is also a test that reads `gates.py`'s own source and asserts it mentions no `httpx`,
no `Scope.`, and no `sqlalchemy` — the independence is a property of the module, not just of
how the tests happen to be written today.

### Routing is a table, and a sequencing violation never proceeds "just this once"

An LLM that picks agents is non-deterministic, untestable, and adds nothing to a problem this
simple. More to the point it has to be auditable: somebody investigating why a household was
never visited needs to read the rule that should have sent somebody.

The dangerous failure is not a wrong route, it is a route that fires **early**. So each route
carries the facts that must already be true, and `route()` returns three distinct outcomes —
**fired**, **skipped** (the predicate did not hold, ordinary), and **refused** (it should
have run and could not). Collapsing the last two would hide exactly the distinction an
incident review needs.

A refusal raises, audits, and routes to human review.

### Conflicts escalate, and `Escalation` has no resolved state to reach

`touches_life_safety_or_money` returns **True unconditionally**, and the docstring says why
that is not a stub: every conflict kind the platform can produce sends a crew or moves money,
and an unanticipated kind is the one least likely to be safe to resolve automatically. The
named set exists so a log can say which known kind it was, not to admit exceptions.

`why_the_other_might_be_right` is required and a proposal without it is discarded whole. A
model that cannot state the counter-case has picked a side and justified it, and a human
reading a confident one-sided proposal adopts it.

The interrupt payload carries both positions with no pre-selection — a screen that
pre-selects the recommendation converts a decision into a confirmation.

### The eval harness gained a section hook in file 17 and it earned its keep here

Nothing new was needed for the supervisor, which is the point: `AgentSpec.eval_sections`
turned out to be the right shape rather than a one-agent special case.

### Still placeholder, and honest about it

- **No `ApprovalStore` implementation.** The supervisor verifies approvals against a
  protocol; nothing implements it over incident-svc's `dispatch_plan` and ledger-svc's
  `approval`. Same position as files 15–17, and the most consequential instance of it: the
  verification is the safety property, and it is currently proved against fakes.
- **The pending-work API does not exist.** Build file 18 specifies
  `GET /agents/pending`, `/pending/count` and the scoped inbox. `gates.payload_for` already
  stamps `waiting_since` on every gate and `age_minutes` computes the SLA figure, so the data
  is there — the endpoints and the scope filtering are not.
- **The e2e correlation test walks the supervisor, not six services.** It asserts one id
  survives every routing decision and both gates against fakes, and its own docstring says
  what it is. A live version needs the adapters; when they exist, that file is where it goes.
- **`test_resume_all.py` proves half its name.** Five threads pause and five resume onto
  their own subjects across a new graph object — which proves nothing lives in the closures.
  It does not prove Postgres round-trips a checkpoint; that needs a container restart.
- **Nothing subscribes the supervisor to the bus.** `consumers/triggers.py` still holds one
  disabled `noop` row. The routing table is the replacement for it and the consumer wiring
  is the last step — deliberately not taken while five of six agents have no adapters, since
  a live subscription would route real events into agents that refuse at their first node.

---

## File 19 is done — the design system, and the decisions inside it

`packages/ui` is now a real design system: one token source of truth, 34 exported
components, a Storybook, and four CI gates. 7,645 lines across `src` and `scripts`.

```
tokens/       6 files   the source of truth; tokens.css and tokens.nativewind.js generated
primitives/   9 files   Button, Input, Textarea, Select, toggles, overlays, Tabs, Toast
data/         2 files   DataTable (virtualised), StatCard, TrendSparkline, EmptyState
domain/       6 files   SeverityPill, TimeSpine, PendingGateBanner, GNDivisionPicker
map/          1 file    MapLibre shell + four layer builders
forms/        1 file    react-hook-form/zod bindings, TrilingualField, OfflineSubmit
stories/      7 files   the catalogue the a11y and coverage gates walk
```

The four gates, all under `pnpm --filter @sarana/ui`:

```
test:contrast        79 declared pairings, WCAG 2.2 AA, plus an exhaustiveness guard
test:i18n-overflow   15 slots x 3 scripts against a width model
test:a11y            axe over all 33 stories, zero violations
test:tokens-sync     regenerates tokens.css/tokens.nativewind.js and diffs
```

### The brief's palette failed its own accessibility floor in three places

The five severity hexes and the interface palette are the brief's, unchanged. But the
*roles* the brief assigns some of them do not meet the floor it also specifies, and the
contrast gate found all three on its first run:

- **The primary button's hover.** The brief names `--signal-400`. White on it is 3.16:1.
  A hover state is not exempt from SC 1.4.3, so a button that lightened would drop its own
  label below AA at the moment the pointer was on it. Hover now *darkens*, to a derived
  `--signal-600`. `--signal-400` keeps its other role as the accent on the dark base.
- **The accent as text on light.** `--signal-500` is 4.81:1 on `--paper-50` but 4.48:1 on
  `--paper-100`, so a link on the page passed and the same link inside a card did not.
  `TEXT_ACCENT` splits the roles: `--signal-500` stays the button fill, light-theme accent
  text reads one step darker.
- **The focus ring.** The brief's `--signal-400` is 2.86:1 on `--paper-100`, under the 3:1
  floor SC 1.4.11 sets — and a focus ring is the one indicator a keyboard-only dispatcher
  cannot work without. `FOCUS_RING` is per-surface: the brief's ring on dark,
  `--signal-500` on light.

Each derived value carries the measurement that forced it, in `palette.ts`.

### The ramp's five hexes are identity colours, not text colours

Measured against the two base surfaces, every one of them fails AA as body text on one
surface or the other, and levels 0-3 fail on the dark base — which is where the console
actually runs:

```
level  base       on --ink-900   on --paper-50
0      #4A5568         2.49            7.33
1      #C9A227         7.74            2.36
2      #D97706         5.88            3.10
3      #DC2626         3.88            4.70
4      #7F1D1D         1.87            9.75
```

So each level carries a derived `bg`/`fg`/`border` triple per surface, and the raw hue is
kept for the map marker and the card rule. `fg` was solved to 4.75:1 on its own `bg` —
headroom above the floor, so a rounding change cannot silently drop the gate — and
`border` to 3.2:1 against the *tightest* surface the chip can sit on. Solving the light
borders against `--paper-50`, which is the obvious thing to do, put all four of them at
2.98:1 on a card. The gate caught that too.

### Level 4 is a fill, and the thing that inverts is the label

Levels 0-3 render as a tinted chip; level 4 renders as a solid deep-red fill. Lightening
`#7F1D1D` far enough to read as text on the dark base lands it within a few percent of a
lightened `#DC2626`, so the two loudest levels would become the hardest pair on the ramp
to tell apart — exactly the wrong way round.

What actually separates it is not the fill. On the dark base every chip background is
dark, level 4 included: the fills sit within 1.32:1 of each other. The *label* is what
inverts — level 4 reads near-white while every tint reads mid-toned, a separation of at
least 2.44:1 on dark and 4.7:1 on light. A test asserts that. Its first version asserted
the fill instead, and was wrong.

### The ramp is not discriminable in greyscale, and a test says so on purpose

Ochre, amber and red at one tint lightness land within **1.06:1** of each other.
Separating them would mean abandoning either the brief's five hues or a uniform tint
lightness. The system carries the meaning in a shape and a word instead, and
`tokens.test.ts` holds a test asserting the tints are *within* 1.2:1 — so anyone proposing
to drop the shape or the label from `SeverityPill` sees the number first, and so that if
the ramp is ever re-tuned to be luminance-separated the test fires and says the shape rule
can be relaxed.

`SeverityPill` has no `showLabel={false}`, no icon-only variant and no compact mode that
drops the shape. `SeverityDot` exists for the map, and its `label` prop is required.

### "Every token pairing" is a declared contract plus an exhaustiveness guard

The raw cross product is not the right set — `--sev-1-fg` on `--sev-3-bg` is not something
this system draws. So `pairings.ts` declares the 79 pairings that actually render, and
`unpairedTokens()` fails on any colour token appearing in no pairing at all. A token can
escape the gate only by not existing.

Two floors, because WCAG has two: 4.5:1 for text, 3:1 for the boundaries that identify a
control. The brief says 4.5 for everything; where the brief and the standard disagree the
standard wins and the deviation gets a comment. There are four exemptions, each with a
reason, and three tests police the exemption list itself: every reason must be long enough
to be an argument, no exemption may name a pairing that now passes, and **no text pairing
may ever be exempted**.

### The type scale is where the trilingual commitment is actually spent

Sinhala gets +0.15 line-height and a 1.06 size uplift at body sizes; Tamil +0.12 and 1.04.
Sinhala takes the larger leading because its ascender/descender range is the widest of the
three, and at Latin leading the ේ of one line touches the ු of the line above. The uplift
stops above `base` — scaling a 44px headline by 1.06 pushes a three-word Tamil title onto
a second line. Tracking is Latin-only, scoped to `:lang(en)`, because Sinhala and Tamil
glyphs join and letter-spacing breaks the join.

Nothing switches a font in JavaScript. Selection is `:lang(si)`/`:lang(ta)` in
`tokens.css`, which is the only thing that works in a static export and on a printed
page — and the public dashboard is printed.

### The overflow gate is a width model, and it says so

jsdom has no layout, so `test:i18n-overflow` estimates rendered width from code-point
count, a per-script mean advance and the per-script size uplift, then measures it against
the slot budget each component actually gets. It catches the regression it is built for — a
translation growing past its slot — and it does not catch a layout that breaks for another
reason. A real pixel measurement needs a browser; that is the visual regression suite, and
it is **not built** (see the gaps below).

It is worth running just to read the report. The Sinhala DS-division label is **2.98x** its
English equivalent, and the Tamil primary-button label is 1.98x.

### axe runs over the story catalogue, and colour-contrast is disabled there on purpose

`test:a11y` discovers every named export of every `*.stories.tsx` and runs axe on it.
jsdom has no cascade, so axe's `color-contrast` rule cannot evaluate anything and is
disabled explicitly rather than silently skipped — colour is gated by `test:contrast`,
which is stronger, because it covers both surfaces and every state rather than only what
happens to be on screen.

The hole in a discovery-based sweep is a component with no story, which the sweep passes by
never seeing. `coverage.test.ts` closes it from the other direction: every exported
component must appear in a story, with a reasoned exclusion list that is itself policed for
staleness. It caught six wrong exclusions on its first run.

### Not every component is a client component

`'use client'` is on the 18 modules that hold a hook, a browser API or a function prop.
`badge`, `skeleton`, `severity-pill` and `trust` deliberately do not have it, so the
severity chips, the mock-data badge and the audit trail stay server-renderable — which is
what keeps the public dashboard's pages static, and that is the whole point of that app.

### Three things that were broken and are now fixed

- **`formatDate` returned US-ordered dates.** CLDR gives `en-LK` the US order, so
  `formatDate` returned `Nov 28, 2025` while its own docstring said `28 Nov 2025`. Every
  situation report and press release in Sri Lanka is day-first. The tag is now `en-GB` for
  date and time; money stays on `en-LK`, where only the grouping matters and it is the
  same in both. `datetime.ts` had **no tests at all** — it has 11 now, which is how this
  was found.
- **Both Next apps failed `next build`.** `@sarana/ui` and `@sarana/ts-shared` are
  `"type": "module"` and import each other as `./tokens/index.js` while the file is
  `index.ts` — which is what TypeScript mandates for ESM and what `tsc` and Vite both
  understand. Webpack does not. `resolve.extensionAlias` is now set in both
  `next.config.ts`. Turbopack handles it natively, so `next dev --turbo` worked either way
  and only the production build broke, which is the worst place to find out.
- **`pnpm lint` was already failing before file 19 started.** `tests/perf/resolve.js` is a
  k6 script and k6 injects `__ENV`; eslint had no globals declaration for it. Now it does.

### Storybook is not the gate

The a11y addon is installed so a reviewer sees violations while looking at a component, but
`pnpm test:a11y` is what blocks a merge. An addon panel nobody opens is not a check.

### Still placeholder, and honest about it

- **No visual regression suite.** The brief asks for one. It needs a real browser —
  Playwright plus a baseline set — and neither exists. The `test:i18n-overflow` model is a
  deliberate stand-in for the one regression that matters most, not a replacement.
- **The per-script advances are measured averages, not font metrics.** `MEAN_ADVANCE` in
  `overflow-budgets.ts` was taken over the seeded UI strings. No font files are vendored,
  so nothing computes a real advance width.
- **No fonts are vendored or self-hosted.** The stacks name Instrument Sans, Noto Sans
  Sinhala, Noto Sans Tamil and IBM Plex Mono with real fallbacks, and nothing loads them.
  On a machine without them, the Sinhala and Tamil metrics are tuned for faces the browser
  is not using.
- **`MapShell` has never rendered a map.** MapLibre is an optional peer, dynamically
  imported. The layer builders are pure and unit-tested; the shell itself needs a WebGL
  context and a tile server, and `NEXT_PUBLIC_SARANA_MAP_STYLE_URL` points at nothing yet.
- **Nothing consumes the NativeWind preset.** `tokens.nativewind.js` is generated and
  correct; file 22 is what reads it.
- **`next build` cannot finish on Windows without Developer Mode.** Compilation and static
  generation both succeed; the `output: 'standalone'` trace-copy step then fails with
  `EPERM` creating symlinks. Pre-existing, environmental, and unrelated to app code.

---

## File 20 is done — every route the brief names, and the five gaps it closed to get there

What exists: the app shell, the gateway, sign-in, step-up on its own screen, the common
operating picture, **both human gate screens with the agent's reasoning attached**, the
impact forecast board, the alert composer with map-based area selection, the mandatory dry
run and the send behind it, the delivery-gaps panel with its map, the incident and alert
lists with linked reports, the audit ledger with CSV export and the published anchors, the
anomaly disposition workflow, the review and grievance queues with assignment and
resolution, the entitlement approval detail, the user directory and role catalogue, the
web fallback for filing an assessment, and the degraded states. **60 static pages build
(20 route entries x 3 locales), and no route renders `NotBuilt`.**

```
app/[locale]/           login, totp, /, /ops, /ops/incidents(+[id]),
                        /ops/dispatch(+[planId]), /ops/alerts(+[id], +[id]/delivery),
                        /ops/alerts/new, /ops/forecast, /ops/review,
                        /field/assessments(+/new), /approvals(+[id]),
                        /disbursements(+[id]), /grievances,
                        /audit, /audit/anomalies, /audit/chain, /admin
app/gateway/[...path]   the BFF proxy - one origin, five services
src/lib/                gateway client, queries, schemas, session, step-up, auth actions
src/components/         shell, gate banner, both gates, route map, forecast board, alerts,
                        composer, area selector, quiet hours, dry run, incidents, linked
                        reports, audit, chain, directory, assessments, queues
messages/               579 keys x si/ta/en, gated by verify-i18n
e2e/                    93 Playwright tests, including 24 routes x 3 scripts for overflow
```

### Five backend gaps closed, and why each was blocking a screen rather than a nicety

Every one of these was a case of data the platform already held and no endpoint returning
it. None needed a migration.

**`GET /dispatch-plans/{id}` now returns the reasoning.** The factor breakdown and the
`unservable` list have been in `incident.dispatch_plan.route` since file 16 —
`Plan.as_route_column()` writes exactly that shape, and `_GET_PLAN` was already selecting
the column. `PlanSummary` did not expose it, so the gate screen rendered a degraded banner
in every case and the brief's "expanded by default" requirement could not be met at all.
`PlanDetail` is separate from `PlanSummary` rather than a widening of it: the list endpoint
is polled every five seconds for the banner count, and sending every factor breakdown on
every poll would make the cheapest query in the console the most expensive one.

**`GET /incidents/{id}` now joins its reports.** Its docstring promised "its linked reports
and triage factors" from the day it was written and the SQL joined none. It now returns the
reports with their transcriptions — original-language text, detected language, confidence,
audio key — and the incidents in the same dedup cluster. Three reads rather than one join,
because reports and siblings are both one-to-many and a single statement would multiply the
incident row by their product.

**`GET /impact-forecasts` and `GET /anticipatory-triggers` on agent-svc.**
`hazard.impact_forecast` has existed since file 04 and nothing exposed it, so the forecast
agent was writing to a surface no human could read and `/ops/forecast` rendered "not built".
`DISTINCT ON` gives the latest run per division; `/history` serves the rest, because "did
we see this coming" cannot be answered from the current row alone.

**`GET /admin/users`, `GET /admin/roles`, and grant/revoke on core-api.** The `/admin`
screen named user and role administration and had nothing to build on. Reading is
`admin:read`; granting and revoking are `system:admin` **plus a fresh second factor**,
because a role grant is how somebody acquires `disbursement:release` — it is the quietest
privilege escalation on this platform. The grant is checked against the granter's own area
with the same segment-aware containment RLS uses, refuses a role code the platform does not
define, and requires a stated reason. `scopes` on both endpoints is derived from
`ROLE_SCOPES`, the table `require()` authorises against, so a reviewer reading that screen
is reading what is enforced rather than a description of it.

**`GET /responders` gained a response model.** It was untyped, and the console had guessed
a `callsign` field this service has never had. The guess failed at the zod boundary and
quietly emptied the responder list on the dispatch gate — the plan looked like it had no
responders, on the one screen where that matters.

### Two finished screens were invisible, and a test now stops it recurring

`/approvals` was gated on `entitlement:approve` and `/admin` on `admin:write`. **Neither is
a scope this platform has ever defined** — the real ones are `entitlement:approve_ds`,
`entitlement:approve_district` and `system:admin`. Both screens were built, tested and
working at their URLs, and no user could reach either from the navigation.

The failure is silent by construction: `principal.scopes.includes('admin:write')` is simply
false for everybody, so the link never renders, nothing errors and nothing logs.
`tests/auth/test_console_scopes.py` now parses the `NAV` table out of `app-shell.tsx` and
asserts every scope in it is a real `Scope` **and** that some human role holds it — a real
scope only machines hold is the same failure with a subtler cause. TypeScript cannot import
the Python enum, so the check runs from the side that owns the vocabulary. `scopes` is now
a list and any-of: an approver holds the DS scope or the District one and rarely both.

### `verify-i18n` now checks the code against the catalogue, not only the catalogues against each other

Completeness compares si, ta and en to one another, so **a key missing from all three
passes**. `t('totpHint')` where the catalogue says `totpPrompt` renders the literal string
`auth.totpHint` to every user in every language — a worse failure than a missing
translation, because it is wrong in the language the author speaks and so is the one they
are least likely to notice.

It was found by the accessibility sweep rather than by the i18n gate, which is the wrong
place to find it. The script now also resolves every statically readable `t('key')` against
the catalogue: 704 uses, 7 dynamic and reported as unchecked rather than guessed at. It
caught a second broken key immediately.

Bindings are resolved **positionally**. One file routinely holds several components each
with its own `const t = useTranslations(...)` on a different namespace, and matching by name
alone resolves every call against whichever declaration happened to be last — which reports
dozens of real keys as missing and buries any genuine finding.

### Every route, in three scripts, checked for overflow in a real browser

The brief asks that "every route renders correctly in si, ta, and en with no overflow
(visual regression)". `e2e/layout.spec.ts` is that gate: 24 routes x 3 locales, with the
gateway populated rather than empty — an empty state is the layout least likely to
overflow, so a suite that measured those would pass while every populated screen was
broken.

**It measures overflow rather than comparing pixels, and that is a decision.** Baselines
are captured on one operating system with one set of installed fonts; this repository is
developed on Windows against a CI that is not, so every baseline would differ for reasons
that have nothing to do with the console — the suite the e2e config already warns about,
one that fails for unrelated reasons and nobody runs. And a screenshot diff flags *any*
change, so the signal for the one failure that matters would arrive buried in noise from
every intentional edit.

The failure that matters is specific: a Sinhala or Tamil string breaking a layout that fits
in English. Two assertions per route per locale — the document does not scroll sideways, and
no element clips its own content. Containers that scroll by design are excluded, as is
anything one pixel wide, which is how `sr-only` works.

This complements `packages/ui`'s `test:i18n-overflow` rather than replacing it. That gates
15 slots against a width *model* and can run without a browser; this asks the same question
of whole screens where the real font metrics live.

**The detector is tested against a deliberate overflow before it is trusted.** A gate that
has only ever passed is indistinguishable from one that cannot fail, and this is a
hand-written DOM walk whose every exclusion is a chance to exclude the thing it should
catch. That is not hypothetical: the first version tested the wrong node for visual hiding
and reported the skip link on 22 of 24 routes. A guard one clause broader would have
reported nothing and gone green while measuring nothing.

### The sign-in page rendered the whole console shell, and polled the gateway signed out

`login/layout.tsx` returned only its children, on the belief that a nested layout *replaces*
the parent. Nested layouts in the App Router **compose**. So the sign-in page rendered the
navigation, the disaster spine and `PendingGates` — which polled `dispatch-plans` and
`entitlements` every five seconds at a browser with no session, producing a steady stream of
401s. That is precisely what that file's docstring said it was avoiding.

Route groups are the mechanism that actually does it, and they are what the brief's own
`/(auth)/login` notation means. The tree is now `(auth)` for sign-in and step-up and
`(console)` for everything behind the navigation. **No URL changed** — a route group is a
file-system device — and all 60 static pages still build.

### Half of every page was translations it could not reach

`NextIntlClientProvider` with no `messages` serialises the **whole** catalogue into every
page. `request.ts` justified loading it whole on the grounds that it was "158 keys and a few
kilobytes"; at 579 keys it was ~22 KB of characters and **half the HTML of the sign-in
page**, which can reach two namespaces of twenty-five.

The server still loads everything — a server component may format any message, and splitting
the *locale* load is the one thing this product must not get wrong. What is narrowed is only
what crosses to the client, and only along a boundary the route tree already draws:
`(auth)` gets four namespaces, `(console)` gets all of them. Per-page lists were rejected as
a second place to forget, and forgetting one renders a key path to a district office.

The sign-in page went from **47.4 KB of HTML to 12.3 KB** (15.2 → 3.7 KB gzipped).

### A third phantom scope, in the landing redirect

The same `entitlement:approve` that hid `/approvals` from the navigation was also in the
root page's landing table, so a DS approver signing in fell through to the next matching row
and arrived on the operator's map rather than on the queue holding their signature. Silent,
like the others. `tests/auth/test_console_scopes.py` now parses that table too, and asserts
both approval levels land on `/approvals`.

### The dispatch gate screen, now that it has something to show

- **The factor breakdown is inline and expanded**, not behind a popover as it is on the
  queue. The queue's job is comparison across many rows at a glance; this screen's job is
  one decision made properly, and the whole argument has to be readable without a click.
- **`unservable` sits above the decision**, in the warning band, with a Playwright test
  asserting its bounding box is above the approve button's. It is the incident nobody is
  going to, and a dispatcher who reaches the button before that list has been shown it too
  late.
- **Null reasoning and empty reasoning are different claims**, and the schema keeps them
  apart. Null means nothing recorded a reason — the honest state for a plan proposed
  outside the triage agent — and the degraded banner stays for it. An empty factor list
  under a "why these are ranked here" heading would instead say the agent weighed nothing.
- **The route is drawn and blocked segments are not.** There is no road network anywhere in
  this platform, so a blocked-segment overlay would be a drawing rather than a fact. The
  line joins the stops in the solver's sequence and the screen says that is what it is.

### The dry run is mandatory, and the console is the only thing that can enforce it

`alerting-svc` will accept a dispatch without a dry run — the dry run takes no transport at
all, so nothing server-side knows whether anybody looked. That makes `/ops/alerts/[id]` the
only place the rule can live, and it is why the result is **cleared before** each new call
rather than after: a count from ten minutes ago is worse than no count, because it looks
like diligence.

The cap comparison is the server's `exceeds_cap`, not one recomputed in the browser: a
second copy of a threshold that exists to stop twenty million messages would eventually
disagree with the first, in the direction that lets the send through. Over the cap, a typed
reason is required and goes to the server with the dispatch.

### Quiet hours are mirrored into TypeScript, and the mirror had a half-hour bug

The composer has to say *while the message is being written* that a watch-level alert at 2am
will be held until 06:00. There is no alert yet to ask the server about, so the rule from
`agent_svc.agents.warning.channels` is mirrored — the same trade as the SMS segment count,
and worth it only if the two agree.

`quiet-hours.test.ts` walks a full day in Colombo local time and caught a real bug on its
first run: computing the 06:00 release by zeroing the UTC minutes lands on **06:30** in
Colombo, because the offset is +5:30. The hour was right and the minute was wrong, which an
hour-only assertion would have passed. It is now a minute offset from the current Colombo
wall clock, and the test asserts the minute.

### The forecast board says which rows a model produced

`method` is `RULE_THRESHOLD` or `MODEL` on every row, and a banner above the table when
nothing on it came from a model. This is the same failure the triage queue's `assisted` flag
exists to prevent, one loop further upstream: a threshold crossing presented as a prediction
is trusted more than it has earned.

Impact class **does** use the severity ramp, unlike delivery confirmation or queue age. It
is a hazard grade — 4 is the evacuate line — and it is the one derived number on the console
that legitimately borrows those five colours.

Every driver is rendered including one the screen has never seen. The table's CHECK requires
`drivers` non-empty for exactly this reason, and dropping an unrecognised key would silently
omit the term the model just started using.

### The map draws four layers now, and still names what it cannot

Incidents, responder positions, and division boundaries shaded by impact class; delivery-gap
shading lives on the delivery panel where an alert scopes it. Boundaries are fetched **one
division at a time and only for divisions with an incident in the current queue** — bounded
by the size of the event rather than the size of the country — and the layer is off by
default because each visible division costs a request.

Shelters with occupancy are still named as absent: nothing in this platform holds shelter
positions or capacity. A hidden layer is fed an empty collection rather than removed,
because removing and re-adding a layer loses its paint state and its place in the draw
order.

The delivery-gap layer uses a **single-hue sequential ramp, never the severity ramp**. Low
confirmed delivery is a coverage figure; painting a division dark red because its receipts
have not arrived would say the hazard there is worse than next door. A division with nothing
targeted is not on the map at all — a fraction over a zero denominator is not a low number,
it is no number.

### The gate banner counts both gates, and the sound is real

It counted dispatches only, because nothing could list entitlements awaiting release. It now
polls both and renders them as **two banners rather than one summed count**: "3 waiting"
spanning a dispatch and two releases tells a dispatcher nothing about whether any of it is
theirs, and the two go to different people.

The sound is a Web Audio tone — no asset and no network, because an operations room on a
degraded connection is exactly when it must work. Arming is a click, which browsers require
before audio may play at all; a banner that armed itself would be silent and would *look*
armed. `pending-gates.test.tsx` pins both thresholds by the minute, including that the
banner escalates on its own timer with nothing touching the screen.

### Role administration is behind the same second factor as the money gate

Granting a role is how somebody acquires `disbursement:release`. The console collects a
TOTP and a written reason, the server refuses without either, and the dialogue shows the
scopes a role actually confers before it is granted — a role code is a name; the scopes are
the thing. A role carrying a human gate is marked wherever it appears.

The role catalogue is read-only and has to be: a role is a bundle of scopes defined in
`sarana_shared.auth.scopes` and enforced from there, and a console that could edit one would
be editing the authorisation model at run time.

**The gov-mock scenario controls are still not driven from here**, and the tab says so with
the commands that do drive them. gov-mock impersonates the Department of Meteorology, NBRO,
the NDRSC and three payment rails; it is deliberately absent from the gateway's service map,
and a console able to advance its clock is a console able to make the platform believe a
cyclone made landfall.

### `/field/assessments/new` is built, and built to be visibly worse than the app

The brief names the route and a dead handset is a real situation. It files with
`evidence_photo_uris` and `latitude`/`longitude` null, and says so **above the form** rather
than at the button: an officer should decide whether to use this screen knowing what it
cannot do.

No position is recorded rather than the desk's. Those fields mean *where the officer stood*
and exist so an assessment filed from thirty kilometres away can be flagged — sending the
desk position would satisfy the field and defeat the check. The screen says the check cannot
run on this record, which is better than quietly passing it. The idempotency key is
generated once per form rather than per click, so a double-tap replays instead of filing two
assessments for one household.

### The production build works everywhere now, and that unblocked the rest of the budget

`output: 'standalone'` is the deployment artefact (ADR-010) and it is still what `pnpm build`
produces. It is now behind `SARANA_BUILD_STANDALONE`, because emitting it creates symlinks
and that fails with `EPERM` on Windows **after** compilation and all 60 static pages have
succeeded. `pnpm build:local` skips only that step.

The consequence of not having it was larger than a failed command: nothing could run
`next start`, so nothing could measure against a served production build — which is what
file 20's fourth DoD command needs. No Dockerfile consumes the standalone bundle yet (file
25 has not started), so until then the flag cost nothing and blocked everything.

### The performance budget is measured, and one half of it fails for a reason worth stating

**The JS budget is a real gate and it passes.** It reads `app-build-manifest.json`, gzips
every chunk each route loads, and asserts per route. Heaviest is `/admin` at 205.9 KB
against a 250 KB budget; `/login` is 129.9 KB and `/ops` 205.6 KB.

It **refuses to measure a development build**. `next dev` and `next build` share one
`.next`, so running `pnpm dev` or the e2e suite replaces the production manifest with a
development one - and development chunks are unminified and unsplit, so the table comes out
in megabytes and every route fails by an order of magnitude. That is the worst failure a
budget gate can have: not a crash but a plausible table of wrong numbers, sending somebody
after a bundling regression that does not exist. It happened once here, which is why the
check is explicit and names the fix.

Those numbers are ~45 KB lower than they were, from a one-line fix: **neither `@sarana/ui`
nor `@sarana/ts-shared` declared `sideEffects: false`**. Without it webpack must assume
every module in a package has side effects and cannot drop the unused ones, so importing
`Button` from the barrel pulled in every Radix primitive the design system exports. Both
packages are pure components and tokens — no CSS import, no module-scope work — so the
declaration is simply true, and it took 54 KB off the sign-in route and ~43 KB off every
console route.

**LCP is measured and reported twice, because one number alone misleads in both directions:**

```
  simulated  2415 ms   budget 2000 ms
  observed    199 ms   unthrottled, on this machine
```

The page paints in 159 ms. The 2362 ms is Lighthouse modelling that same page arriving over
150 ms RTT at 1.6 Mbps with the CPU slowed fourfold, and under that model **transferred
bytes are the whole story** — 196 KB for the login page, of which roughly 100 KB is React
and the Next runtime before a single line of application code. Reporting only the simulated
figure makes a fast page look broken; reporting only the observed one makes every page look
fine on a reviewer's laptop and says nothing about a district office.

So the script prints both, asserts on the simulated one because that is the connection the
brief names, and on failure prints the transfer total and the framework floor — because a
number that does not say where it went is a number somebody will try to fix in the wrong
place. **On this stack a 2.0 s simulated LCP is not reachable for any App Router page**, and
the console is now at the low end of what it does allow.

Two changes are worth keeping regardless of the gate: the tree-shaking fix above, and
narrowing the client message catalogue (below). Neither moved the simulated figure much,
which is itself the finding - at 196 KB transferred with a ~100 KB framework floor, this
number is not application-shaped.

`start:local` exists alongside `build:local` and the pairing matters. `next start` re-reads
`next.config.ts` in a fresh process, so a build made without the standalone output and a
start made with it disagree: the server warns, then throws `Cannot find module './chunks/…'`
for the pages-router documents. The App Router keeps serving, so it presents as a stream of
errors in the log beside pages that look fine.

### What the e2e suite proves, and what it does not

93 Playwright tests run against `next dev` with the gateway routes intercepted in the
browser, not against a booted platform. That is a trade, not a shortcut: the flows these
protect are properties of the console, and making them depend on six Docker services, a
seeded Postgres and a working TOTP secret would produce a suite that fails for reasons
unrelated to the console and that nobody runs.

So they do **not** prove that `incident-svc` refuses an approval without a step-up stamp, or
that `ledger-svc` refuses a release with an open grievance. Those are server properties,
tested in the Python suite against a real database. They prove the console asks for the
second factor, will not approve on Enter, shows the approver a blocking grievance before the
button, will not send an alert nobody has dry-run, warns on a rule-ordered queue that says
`assisted: false`, and puts the unservable list above the approve control.

### Still placeholder, and honest about it

- **A drawn polygon that snaps to boundaries is not built.** Area selection works by GN
  division, DS division and district. A lasso needs every candidate boundary in the
  viewport and geometry is served one division at a time out of ~14,000; one that snapped
  to nothing would be worse than none, because the operator would believe they had selected
  divisions when they had drawn a shape.
- **Audio is not playable.** `raw_audio_uri` is an object key and media signing is not wired
  (file 08). The screen says a recording exists and cannot be played here, rather than
  rendering an `<audio>` that fails silently — an operator who presses play and hears
  nothing concludes the recording is empty. When the store is wired and the key becomes an
  http(s) URL, the player appears with no change to this code.
- **Shelter positions and occupancy do not exist.** No table holds them. Named on the map as
  absent rather than offered as a toggle that does nothing.
- **The spine still plots two milestones, not six.** Declaration and landfall are readable;
  forecast issued, alert dispatched, first incident, peak queue depth and first disbursement
  each need a query that does not exist.
- **The visual regression gate measures overflow, not pixels** — see below. A screenshot
  baseline suite is the literal reading of the brief and would be the wrong tool here.
- **Still no SSE anywhere.** The console polls. `LIVE_INTERVAL_MS` in
  `apps/web-ops/src/lib/queries.ts` is the one place that changes when a stream exists.
- **The simulated LCP budget is not met, and is not reachable on this stack.** 2415 ms
  against a 2000 ms budget, with 196 KB transferred of which ~100 KB is React and the Next
  runtime. Observed LCP is 199 ms. Both figures are printed by the gate. Closing it would
  mean changing framework or dropping to a non-hydrating page for sign-in, and neither is a
  file 20 decision.
- **`pnpm build` still cannot finish on Windows**, by design rather than by accident: it
  emits the standalone deployment bundle and that step needs symlinks. `pnpm build:local` is
  identical without it and completes everywhere. Nothing consumes the standalone bundle yet
  — file 25 has not started — so when it does, that Dockerfile is the thing that must run
  `build`, not `build:local`.

---

## The SMS segment count now exists in TypeScript, and it is pinned to the Python one

`packages/ts-shared/src/format/sms.ts` mirrors `sarana_shared.domain.sms`. It is the only
duplicated logic in the repository and it earns the duplication: the alert composer has to
show the segment cost for all three languages **while the operator is typing**, before any
draft exists to ask the server about. A preview that appeared only after drafting would
tell an author their Tamil message is three segments at the point it is too late to reword
it.

The mirror is not trusted on assertion. `sms.test.ts` runs ten strings through the
TypeScript implementation and asserts the exact numbers the Python one produced for the
same strings - encoding, units, segments and headroom - copied from its output. If the two
diverge the test fails, and the Python one is right: it is what the gateway adapter counts
with.

The numbers worth knowing, from that fixture:

```
                                            encoding  units  segments
"Flood warning for Ganga Ihala Korale."     GSM7        79      1
the same sentence in Sinhala                UCS2        79      2
the same sentence in Tamil                  UCS2        91      2
```

Same warning, same meaning, twice the segments in the two languages most of the country
reads. That is the asymmetry the module exists to make visible, and it is why the composer
shows all three side by side rather than behind a tab.

---

## The alert composer, and the call it cannot make

`/ops/alerts/new` does template selection, parameter filling, the live trilingual preview
with per-language segment costs, free text that visibly forces sign-off, and the mandatory
dry-run notice. Five Playwright tests cover it.

**It drafts, and drafting is deliberately not sending.** `GET /hazard-events` closed the
gap that once stopped it creating a draft at all. The screen now creates one and stops:
dispatch is a separate call behind a mandatory dry run on `/ops/alerts/[id]`, and one
button that drafted and sent is how a national fan-out happens by accident.

Three decisions inside the screen:

**Unpublished templates are listed, not hidden.** All twelve seeded templates are `DRAFT`
with no reviewer signatures, deliberately - a human must sign each language before an
alert can be dispatched. An operator who cannot find the flood template needs to know it
is awaiting a Tamil signature, not that it does not exist. The empty state names each
template and which signature it is waiting for.

**Parameters are read from the template body, not from a declaration.** The union across
all three languages, so a placeholder present only in the Tamil body is still a field. The
alternative renders `{shelter_name}` literally to Tamil readers and to nobody else, which
is the kind of bug that survives review.

**Two segments blocks the draft.** The segment ceiling is a release gate on templates in
CI, and it is the same gate on an instance here. The e2e test pushes the Sinhala rendering
over with free text and asserts the draft button disables and the reason appears.

---

## Chain verification is built, and it was never blocked

An earlier note in this handoff said `/audit/chain` was blocked on a missing
range-verification surface. That was wrong: `GET /audit/verify` on core-api has existed
since file 05, takes `from_seq` and `to_seq`, and returns the first divergence with what
was expected and what was found. The screen is now built against it.

Three properties, each with a Playwright test, because each is a way the screen could
quietly weaken the claim it exists to test:

**A green result names its range.** "The chain is intact" over an unstated range is a
claim about nothing. Every result renders `N entries checked, seq X to Y`, so an auditor
who verified a hundred entries does not walk away believing they verified the ledger.

**A red result names the exact divergence.** The `seq`, the reason, the expected hash and
the found hash. "The chain is broken" is not actionable; "entry 4,117 carries a prev_hash
of X where the previous entry hashes to Y" is.

**A chain with no external anchor is reported as such.** The daily Merkle root is computed,
chained to the previous day and published - but `s3_object_lock_uri` is null until an
object store is wired, and that URI is the entire external half of the guarantee. Without
it the chain is verifiable only against a database the operator controls, which is a much
weaker claim than a green tick suggests. The screen counts the unanchored days and says so
above the table.

The published hashing scheme is rendered too, so a verifier reading this page needs no
access to the source.

### Verification is an action, not a poll

`verifyChain` is a plain async call rather than a `useQuery`. A range that silently
re-verified every fifteen seconds would turn a deliberate check into background noise, and
the answer would scroll past unread. The previous result is cleared before a new call, so
a stale green cannot sit on screen while a different range is being checked.

---

## `/field/assessments/new` exists, and is built to be visibly worse than the app

The Field Companion is the real tool: a GN officer assesses damage standing in front of a
house, usually with no signal. This screen exists for the case where the handset is dead,
lost or never issued, and for a DS officer reviewing what their division has submitted.

The brief names `/field/assessments/new` and a dead handset is a real situation, so it is
built - and built so that it cannot feel equivalent to the app. It files with
`evidence_photo_uris` and `latitude`/`longitude` null and says so **above the form** rather
than at the button, because an officer should choose this screen knowing what it cannot do.

No position is recorded rather than the desk's. Those fields mean *where the officer stood*
and exist so an assessment filed from thirty kilometres away can be flagged; sending the
desk position would satisfy the field and defeat the check. Saying the check cannot run on
this record is better than quietly passing it.

The idempotency key is generated once per form rather than per click, so a double-tap
replays the stored record instead of filing two assessments for one household - which is
two entitlements and eventually two payments.

---

## The map draws four layers, and still names the one it cannot

`SituationMap` plots incidents, responder positions and division boundaries shaded by
forecast impact class; delivery-gap shading is on the alert delivery panel, where an alert
scopes it. `GET /responders` was already returning `lon`/`lat` and nothing read them;
boundaries came with `GET /impact-forecasts` giving the class to shade by.

**Shelters with occupancy are still named on screen as not built** rather than offered as a
toggle. Nothing in this platform holds shelter positions or capacity, and a toggle that does
nothing is worse than an absent one: an operator who switches one on and sees an unchanged
map concludes there is nothing there.

A hidden layer is fed an empty collection rather than removed. Removing a layer and
re-adding it loses its paint state and its position in the draw order, so a toggle would
silently change how the map looks the second time it is switched on.

**An incident with no coordinate is not placed, and the count is shown.** A report naming
a village and nothing more is real, and it stays in the queue and in the accessible list.
Placing it at the division centroid would invent a precision the report does not have;
placing it at (0, 0) would drop it in the Gulf of Guinea. Seven unit tests cover the
transform, including the one that matters most — coordinates go out longitude-first,
because latitude-first puts every Sri Lankan incident in the Indian Ocean off Somalia,
which looks plausible enough on a zoomed-out map that nobody catches it until someone is
sent there.

**Boundaries would be per-division, not bulk.** `core-api` serves geometry one division at
a time and there are ~14,000 of them, so the boundary layer — when built — fetches only the
divisions that have an incident in the current queue. Bounded by the size of the event
rather than the size of the country.

### The axe sweep caught a critical bug in the pane splitter

The three-pane divider is `role="separator"` and focusable, which in ARIA terms makes it a
window splitter — and a splitter must carry `aria-valuenow` with its bounds. Without them a
screen reader announces "separator" and nothing else, so a keyboard user can move the
divider and never learn whether it moved. It now reports its position. This is the second
real defect the a11y sweep has found rather than confirmed, and it is why the sweep runs
over whole screens in three locales rather than over components in one.

---

## The third gate: `/admin` and the trilingual template review

There are two *mandatory* human gates in SARANA and this is not one of them - but it is the
gate that stands between twelve machine-translated life-safety messages and a district, and
until now nothing in the console could open it. All twelve seeded templates are `DRAFT`
with no reviewer signatures, so the alert composer had nothing to offer and said so.

`/admin` now signs and publishes them. Three rules, all with Playwright tests:

**Publish is unreachable until both signatures exist.** `ledger-svc`'s database predicate
refuses it and the endpoint checks before that; this is the third layer, and it is here so
a reviewer never presses a button that was always going to fail.

**The language is chosen explicitly, never inferred from the reviewer.** Two buttons, each
naming its language in that language. Someone who reads both still has to say which one
they are signing for.

**The reviewer's identity is never in the request body.** `POST /templates/{id}/review`
takes only a language and reads the signer from the token. A test asserts the body carries
no reviewer field, because a review somebody else can attribute to you is not a review.

One test is named after the failure the whole platform exists to correct: *one signature is
still not enough*. Sinhala signed and Tamil not is exactly the state the 28 Nov 2025 DMC
press conference went out in.

The cost schedules are read-only on the same screen. A schedule is what every entitlement
is calculated from, and changing one from a console during an incident would silently
re-price work already done - versions are added by migration, deliberately. The published
formula is rendered per line, because a household told what it is entitled to can read the
same formula the system used.

### The map now updates in place

`MapLike` in `packages/ui/src/map/map-shell.tsx` gained `getSource` returning a typed
`GeoJsonSourceLike`, so the console pushes new features with `setData` on each poll rather
than adding the source once and never again. Re-adding a source that exists throws, and it
drops the layer's paint state even when it does not.

The GeoJSON is memoised on `rows`, which TanStack Query keeps referentially stable between
polls through structural sharing. Without that the object is new on every render and the
`setData` effect fires on renders that changed nothing.

---

## The queue endpoint returns an object, and the console was reading it wrong

`GET /incidents/queue` returns a `QueueResponse` - `{assisted, banner, ordering, entries}` -
not a bare list. The console's zod schema had it as an array, which would have thrown at
the boundary on the first real request. Two things followed from getting it right, and the
second is the one that mattered:

**`assisted` is the only authority on whether an agent ranked the queue.** The console was
inferring it from whether any row carried a score. That inference can never be false:
`incident-svc` computes a score from the published rule for every row that has none,
deliberately, so an unranked incident is not dropped to the bottom of a long queue where
nobody reaches it. So the degraded banner would have stayed hidden while no model was
running, and a dispatcher would have worked a rule-ordered queue believing a model had
ordered it. That is the single most misleading thing this console could do, and it was
doing it. An e2e test now pins it: `assisted: false` with a score on every row must still
warn.

**The ordering rule is named beside the banner.** "Manual ordering" tells a dispatcher less
than `triage-rules-1`. The server's own `banner` string is available but English-only, so
the console renders its own trilingual one and shows the server's `ordering` value beside
it.

### The queue rows now age, and say why they are ranked

Rows past twenty minutes turn `--pending`. Not a severity colour: how long an incident has
waited is a fact about this console's queue, not about the hazard, and painting it amber
would say the hazard got worse. One clock ticks for the whole queue every thirty seconds,
shared rather than per-row - two rows a second apart must not straddle the threshold
because they rendered in different ticks.

The score is a popover trigger showing the per-factor breakdown, sorted by contribution.
A popover rather than a detail pane: an operator comparing row 3 against row 4 has to see
both reasons within a few seconds, and a pane that replaced the context panel would lose
the row being compared against.

### Two layout bugs the e2e suite found

The map pane was `h-full` inside a flex column, so the layer controls and the unplaceable
count were clipped out of an `overflow-hidden` parent - present in the DOM, invisible on
screen. And the e2e incident fixture carried no coordinates at all, which made every
incident unplaceable and would have quietly turned the map tests into tests of the empty
case.

---

## The queue is virtualised, and it tells the truth about its size

A national event puts thousands of incidents in the triage queue, and rendering them all is
how the console becomes unusable on the mid-range hardware an operations room actually has.
Only the rows in view plus six either side are in the DOM.

It stays an `<ol>` rather than becoming a grid of divs, and every row carries `aria-setsize`
and `aria-posinset` with the **real** numbers. A virtualised list that reported the rendered
count would tell a screen reader "item 1 of 12" during an event with 1,203 incidents, which
is worse than no count at all. An e2e test pins it.

## The context pane reads the audit trail

`GET /audit` on core-api takes `subject_type` and `subject_id`, so the selected incident's
history is real rather than a placeholder. Three decisions:

**Ordered by `seq`, oldest first.** The order is the content - an approval that came after a
disbursement is a finding, and only the sequence shows it. `seq` rather than the timestamp,
because two actions in the same millisecond still have an order.

**An agent is named; a person is a type.** `agent_name` where an agent acted, `actor_type`
where a human did. No personal name appears, because the query never selects one - a
stronger guarantee than redacting one here would be.

**A failed audit read is not an empty audit trail.** The pane says the trail could not be
read rather than rendering nothing, because nothing reads as "this incident has no
history".

### `GET /incidents/{id}` now returns what its docstring always promised

It said it returned "its linked reports and triage factors" from the day it was written,
and the SQL behind it selected the incident row and joined nothing. `IncidentDetail` now
carries the linked reports with their transcriptions — original-language text, detected
language, confidence, and the audio key — plus the incidents in the same dedup cluster.

Three reads rather than one join. Reports and cluster siblings are both one-to-many, so a
single statement would multiply the incident row by their product and every consumer would
have to un-fan it; two extra round trips on a detail view is the cheaper answer than a
query nobody can read.

**No column in that query identifies a person.** `sender_msisdn_hash` and
`sender_household_id` are deliberately not selected — a query that never selects a name
cannot leak one, which is stronger than redacting downstream. The LATERAL takes the most
recent transcription per report rather than all of them, because a report re-transcribed
after a human correction has two rows and the older one is the machine's rejected guess.

---

## `GET /entitlements` now exists, and the rule behind it lives in one place

This is the first backend change made for file 20, and it was the only way to finish the
money screens. `ledger-svc` had `GET /entitlements/{id}` and no list, so nothing could ask
"what is waiting" - the console said so on screen rather than rendering an empty list,
because an empty list would have told a district approver no money was waiting when there
might have been a hundred households.

Three decisions inside it:

**`approved_levels` is an array, not a count.** Two approvals at the same level are not two
levels. A queue that counted rows would offer an approver work the gate then refuses, and
an approver who learns that refusals are noise is the one habit a human gate cannot afford.

**`awaiting_release` filters in Python, not in SQL.** Readiness is decided by
`domain.approval.is_ready_to_release`, the same module the disbursement gate refuses with.
A WHERE clause encoding the same rule is a second copy that can drift, and the way drift
presents is exactly the queue-offers-what-the-gate-rejects failure above.

**`released` counts live payments only.** A reversed disbursement is money that came back,
so the entitlement is unpaid again and must appear in the release queue a second time.
Without that clause a reversal would quietly remove the household from every queue that
could pay them.

The rule moved into `domain/approval.py` as `required_levels` and `is_ready_to_release`,
beside `ApprovalState`, so the queue and the gate read the same threshold. **20 parametrised
tests assert the two never disagree** across every amount either side of the threshold and
every combination of recorded levels - that agreement is the whole reason the helper exists
rather than being inlined.

### `/approvals` and the real release queue

`/approvals` shows what each entitlement is still waiting for **by level**: "Needs DS" and
"Needs DISTRICT" go to different people, and a generic "pending" misroutes the work.
Signing requires a second factor, and the screen says plainly that approving is not
releasing - a different person confirms the money should move, and `ledger-svc` refuses a
release by whoever approved it.

`/disbursements` no longer says its queue cannot be listed. It lists what is ready, oldest
first from the server, because the household that has waited longest is the one to reach
first.

---

## `GET /hazard-events` exists, and it unblocked two things at once

The second backend change for file 20, and it was blocking more than it looked.
`hazard.hazard_event` has existed since file 04 with `landfall_at` on it, and nothing
exposed it. That single absence stopped two separate things:

- **The alert composer could not create a draft.** `POST /alerts` requires a
  `hazard_event_id`, so an operator could compose a message, check its segment cost in
  three languages, and then have no way to name the event it was about.
- **The time spine had nothing to anchor to.** `landfall_at` is T+0, and the signature
  element of the design system sat in Storybook and on no screen.

It is read-only on purpose. A hazard event is declared by the forecast agent from a
meteorological feed or by DMC through the inbound path, and a console that could create one
would let an operator invent a cyclone. Closing one is a state transition with consequences
for every alert and incident hanging off it, and it belongs with the agent that owns the
lifecycle rather than behind a button.

It sits on **agent-svc**, which owns the schema, and reads with `incident:read` rather than
an agent scope - everyone who works an incident needs to know which event they are working,
including a GN officer holding no agent scope at all.

### The spine renders nothing between events, which is most of the time

An event under monitoring has no landfall, so `DisasterSpine` draws nothing rather than
anchoring the rail to the declaration time - a fabricated T+0 across the top of every
operational screen would be worse than no rail. `anchorEvent` picks the most recent event
that *has* a landfall rather than simply the newest, so the console is not anchored to a
depression nobody is working yet.

The phase - anticipatory, response, recovery - is derived from the offset and returned as a
**message key**, not a label, so it is never an English word on a Tamil console. Eight unit
tests pin the boundaries, including that landfall itself is response rather than
anticipatory.

Only the milestones the platform can actually date are plotted: the event's declaration and
its landfall. The brief also lists forecast issued, alert dispatched, first incident, peak
queue depth and first disbursement, and none of those has a query behind it. Three hollow
markers labelled with things nothing has measured would be worse than two that are real.

### The composer drafts now, and drafting is still not sending

`POST /alerts` is wired. The screen creates a draft and stops: dispatch is a separate call
behind a mandatory dry run, and one button that drafted and sent is how a national fan-out
happens by accident. The confirmation says the draft still needs sign-off and a dry run.

Division codes go to the server as codes; `gn_division_ids` is sent empty and the service
resolves them. Sending both would be two sources of truth for the same area and a chance
for them to disagree.

---

## Things that will bite you

These each cost real debugging time. They are written down so they cost you none.

### The test suite's flakiest failure is not your code — it is disk

If a run dies with dozens of errors at *fixture setup* saying `Port mapping for container
… and port 8080 is not available`, nothing has regressed. **Zero `FAILED` and many
`ERROR` is the signature.** There are two causes and it is usually the second:

```bash
# 1. A stale reaper from a killed run.
docker rm -f $(docker ps -aq --filter name=testcontainers)

# 2. Docker is out of disk and cannot map ports. This is the usual one.
docker builder prune -af
```

Rebuilding containers eats disk fast — one session of ordinary work consumed 8 GB of build
cache and took the machine from 3 GB free to 0.9 GB, at which point every testcontainer
failed to start. Pruning fixed it immediately.

**Watch this.** `docker_data.vhdx` cannot currently be compacted on this machine: no
Hyper-V on Windows Home, no admin for `diskpart`, and WSL refuses sparse mode without
`--allow-unsafe` over the Postgres volumes. So the space you reclaim lives *inside* the
VHDX and host free space never rises. Run the prune before a long test session, and get a
proper `diskpart compact vdisk` done from an elevated shell when you can.

**There is a third cause, and as of 2 Sep 2026 it is the live one.** Same symptom, neither
of the above fixes it:

```bash
TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/schema   # 52 passed
uv run pytest tests/schema                                     # 13 errors
```

testcontainers asks Docker for ryuk's published port *before Docker has published it*.
`Reaper._create_instance()` calls `get_exposed_port(8080)` immediately after starting the
container; `docker port <id>` on the very same container a second later returns the mapping
fine. It is a race inside testcontainers' own startup, before any SARANA code is imported,
and it is not load-dependent - it reproduces on a completely idle machine.

Diagnosing it: `docker ps -a --filter ancestor=testcontainers/ryuk:0.8.1` after a failed
run shows the orphaned container *with* a healthy `0.0.0.0:NNNNN->8080/tcp` mapping. Each
failed run leaves one behind, so clear them:

```bash
docker rm -f $(docker ps -aq --filter ancestor=testcontainers/ryuk:0.8.1)
```

`TESTCONTAINERS_RYUK_DISABLED=true` is a working diagnostic and is **not** set anywhere in
the repository, deliberately: ryuk is what cleans up containers after a killed run, and
turning it off by default trades this race for a slow leak of stray Postgres containers.
Pinning a newer `testcontainers` is the real fix and has not been tried.

### Vocabularies drift from the schema, silently, and it is always a 500

Three separate times, code produced a value the database's CHECK constraint rejected. Each
one would have been a 500 at the worst possible moment — a citizen's SOS, an alert
dispatch. Each is now guarded by a test:

- `tests/incident/test_vocabularies.py`
- `tests/alerting/test_vocabularies.py`
- `tests/core_api/test_reference_data.py`

**Write one of these for every service you touch.** The pattern is: assert the domain's
set and the schema's set are equal, in both directions.

### asyncpg cannot infer a bare parameter's type

`WHERE (:x IS NULL OR col = :x)` fails at runtime with `could not determine data type of
parameter $1`. Always cast:

```sql
WHERE (CAST(:x AS uuid) IS NULL OR col = CAST(:x AS uuid))
```

### The hierarchy cache holds negative results

`core-api`'s `/admin/resolve` caches misses for an hour. A coordinate looked up before the
seed landed keeps returning 404 afterwards. `make seed` restarts core-api for this reason;
if you load data another way, restart it yourself.

### Two database users, and it matters

Services connect as `sarana_app`, which cannot bypass row-level security. Migrations and
the seed loader connect as the owner. A superuser DSN in `SARANA_DATABASE_URL` silently
disables every policy in the schema.

---

## Architectural decisions taken during the build

Each of these deviates from a build brief. If you disagree, the reasoning is here to argue
with.

### The national scope code is `LK`, not `*`

`sarana_shared.auth.grants.NATIONAL_CODE` was `*`. The database CHECK on `admin.user_role`
requires `'LK'`, and `public.sarana_scope_covers()` tests for `'LK'`. Every national
account — operator, auditor, admin — **500'd on login**, and had login worked, they would
have seen zero rows under RLS.

Aligned on `LK`. Every administrative code begins `LK-`, so a national scope covers the
country by the same prefix rule every other level uses. Guarded by
`tests/auth/test_national_scope.py`, which round-trips through the schema — the gap that
let this survive 334 tests.

### The dispatch gate verifies step-up, not a TOTP in the request

Build file 08 says to verify a TOTP presented with the approve request. `core-api` owns
the MFA secrets; its step-up endpoint verifies the code and stamps `step_up_at` into a
fresh token, and the gate requires that stamp to be under five minutes old.

The guarantee the brief asks for holds — a session alone is never sufficient. Verifying
the code inside incident-svc would mean spreading every dispatcher's MFA secret across
services to re-derive a fact core-api already established.

### No CAP 1.2 XSD is vendored

Build file 09 says to validate against the official OASIS schema. That file is not in this
repository. `domain/cap.py` encodes the standard's structural rules directly, and
`tools/cap_validate.py` takes `--xsd` to run a real schema when you supply one.

Writing an XSD from memory to make a green tick appear would report compliance this code
cannot demonstrate. **Download the real XSD from OASIS and wire it into CI** — that is a
genuine open gap, not a decision.

### Service-to-service credentials do not exist as a mechanism

`incident-svc` must call `core-api`'s `/admin/resolve` on the intake path. `Role.CITIZEN`
holds `incident:write` and deliberately **not** `admin:read`, so the reporter's token
cannot be forwarded — and citizens are the primary reporters. Every report was landing
unplaced behind a silent 401.

**Resolved.** `POST /api/v1/auth/token` is a client-credentials grant against
`admin.service_client`: short-lived, revocable, least-privilege and area-scoped. See the
section above. `tools/seed/service_token.py` is deleted; `make service-clients` provisions
the replacements.

### Delivery states were added to the file 04 schema

`delivery_receipt.status` allowed QUEUED, SENT, DELIVERED, READ, FAILED, EXPIRED. File
09's own example demands three buckets — "1,203 unconfirmed, 865 no channel available" —
and neither `UNKNOWN` nor `NO_CHANNEL` existed.

Migration `alerting_svc_0005` adds both. `UNKNOWN` counts *against* coverage; folding it
into DELIVERED would produce a map claiming a village was warned when nobody knows.

### The brief's state names are not the schema's

File 08 refers to `NEW`, `MERGED` and `DISPATCH_PROPOSED`. The schema has `REPORTED`,
`DUPLICATE`, and no separate proposed state. The database wins; the mapping is documented
at the top of `incident_svc/domain/state_machine.py`.

`DISPATCH_PROPOSED` is deliberately absent — a proposed dispatch is a fact about a *plan*,
which has its own status. Encoding it on the incident too would let the two disagree.

Also: file 08 cites `Scope.DISPATCH_APPROVE`, which does not exist. The human gate is
`Scope.DISPATCH_COMMIT`.

---

## Known gaps in what is marked done

- **Media handling (file 08)** — limits are enforced at presign and object keys are
  generated correctly, but S3/MinIO signing is not wired and EXIF GPS extract-then-strip
  is not implemented.
- **Perf gate (file 07)** — `tests/perf/resolve.js` is written to spec (p99 < 20 ms at 200
  rps) but has never been run. k6 is not installed and the target is unverified.
- **The dispatch gate is wired to the runtime, and off by default (files 12/16/08).**
  `AgentThreadResumer` is real and tested; `SARANA_INCIDENT_RESUME_AGENT_THREADS` turns it
  on and defaults to false. With it off the gate uses `NullResumer` and reports
  `graph_resumed: false`, which is the honest answer for a deployment with the agents
  switched off. It has never been run against a booted agent-svc, because the triage agent
  has no adapters yet and therefore no plan with a real `langgraph_thread_id`.
- **No agent has called a real model yet (files 12/13).** `runtime/models.py` routes tiers,
  tracks spend and retries, and nothing has exercised it against a live provider. The
  forecast agent has two model call sites and both are optional by design — every test and
  every deployment without a key takes the deterministic path. The budget breaker and the
  retry policy are still unproven against a real 429.
- **The forecast agent has never run against the live stack.** Its ports, adapters, replay
  and eval all work; `GET /admin/gn-divisions/exposure` is tested against a real Postgres.
  What has not happened is one `POST /api/v1/agents/forecast/runs` against a booted
  gov-mock and core-api, so the wiring in `main._build_forecast` is reviewed rather than
  exercised.
- **Nothing triggers an agent from an event in a running stack (file 12).** The consumer,
  the trigger table and the idempotency are all built and tested; the single row in
  `consumers/triggers.py` is disabled, because pointing the reference agent at live citizen
  reports would fill the approval inbox with unanswerable questions. File 15 turns it on.
- **Seed data below district level is synthetic.** Provinces and districts are real
  (official codes and names). DS and GN divisions are generated rectangles around real
  district centroids. Never present them as survey boundaries.
- **Anchors have no object store (file 10).** The Merkle root is computed, chained to the
  previous day and published; it is not written to S3 Object Lock unless a store is
  configured. `NullAnchorStore` says so in the logs and leaves `s3_object_lock_uri` null
  rather than inventing a plausible URI. Until it is wired, the chain is verifiable and
  the *external* anchor — the half that survives an operator rewriting the database — is
  not there.
- **Entitlement calculation reads one schedule line (file 10).** `POST /entitlements`
  values the assessment's single category. A household with damage in several categories
  needs several assessments today. The pure calculator underneath already handles multiple
  items and the household cap; the endpoint does not yet pass them.
- **Nothing starts the warning agent from an event (file 14).** `consumers/triggers.py`
  has no row for it. A forecast reaching class 4 does not currently draft an alert; the
  agent runs from `POST /api/v1/agents/warning/runs` only. Adding the row is deliberate
  work, not an oversight — it fans out to real targets on the first generation.
- **Alert fatigue is not suppressed in a running stack (file 14).** The rule is real and
  tested; `NullHistory` is what is wired, because no query over `alerting.alert` per
  household exists yet. It logs a warning on every call.
- **The intake agent has no adapters (file 15).** The graph, the ports and 79 tests are
  complete and run against fakes; there is no `Transcriber`, no `Embedder`, no gazetteer
  client and no `ReportStore`, so `main.py` does not wire it. It cannot process a real
  report yet.
- **There is no gazetteer (file 15).** `geolocate` needs place-name lookup and core-api
  has no such endpoint. `data/seed/reference/gn_division.json` would serve as a first
  one; landmarks below division level need a real source.
- **No per-language WER exists (file 15).** Measuring it needs a held-out set of real
  Sinhala and Tamil audio with human transcripts, which this repository does not have.
  Absent rather than fabricated — see the file 15 section.
- **The triage agent has no adapters, and `NullResumer` still stands (file 16).** The
  graph, its four ports, the OR-Tools solver and 79 tests are complete against fakes.
  What does not exist is an `IncidentSource`/`ResponderSource`/`PlanStore` over
  incident-svc, and the wiring that points `dispatch_gate`'s `ThreadResumer` at
  agent-svc's resume endpoint. The gate's safety properties all hold without it.
- **The anomaly agent has no adapters, and its disposition loop is open (file 17).**
  Detectors, normalisation, redaction and 74 tests are complete against fakes. Nothing
  reads ledger-svc, and `FlagStore.disposition_rates` has no caller - so the real
  false-positive rate ADR-009 requires published is measured against fixtures only.
  Closing it needs the review surface from file 20.
- **Nothing subscribes the supervisor to the bus (file 18).** The routing table is the
  replacement for `consumers/triggers.py`, which still holds one disabled `noop` row.
  Wiring it is the last step and is deliberately not taken while five of six agents have
  no adapters - a live subscription would route real events into agents that refuse at
  their first node.
- **No `ApprovalStore` implementation (file 18).** The gate verification is the safety
  property and it is currently proved against fakes. Nothing reads incident-svc's
  `dispatch_plan` or ledger-svc's `approval`.
- **The pending-work API does not exist (file 18).** `GET /agents/pending` and the
  scoped inbox are specified and unbuilt. `waiting_since` is already stamped on every
  gate payload, so the SLA data is there and the endpoints are not.
- **~~`GET /dispatch-plans/{id}` does not expose the reasoning~~ — closed in file 20.**
  `PlanDetail` now returns `route`, `langgraph_thread_id` and a typed `reasoning` block
  read from the column the triage agent already writes. The gate screen renders the factor
  breakdown and the `unservable` list, and keeps the degraded banner for the case that is
  still real: a plan nothing recorded a reason for.
- **No SSE anywhere (files 07/20).** The console polls. `LIVE_INTERVAL_MS` in
  `apps/web-ops/src/lib/queries.ts` is the one place that changes when a stream exists.
- **No visual regression suite (file 19).** Required by the brief, and it needs a real
  browser. `test:i18n-overflow` is a width *model* standing in for the one regression that
  matters most; it is not a pixel comparison and does not claim to be.
- **No fonts are vendored (file 19).** The three-script metrics are tuned for Noto Sans
  Sinhala and Noto Sans Tamil, and nothing loads them. On a machine without those faces
  installed, the uplift and leading are applied to whatever the browser substitutes.
- **Payment rails are mocks.** Every reference starts `MOCK-`.
- **Nothing here is delivered to a real handset.** The payment notices go out through
  `MockSmsGateway`, like every other channel in Phase 1. The message text, the language
  selection and the delivery accounting are real; the transport is not.

---

## Conventions worth keeping

Absorbed from the codebase rather than invented:

- **Comments explain why, never what.** Every non-obvious constant carries the reasoning
  for its value.
- **Test names are sentences** describing the behaviour, and docstrings say what breaks if
  the rule does not hold.
- **The database is the authority.** Where a brief and a CHECK constraint disagree, the
  constraint wins and the deviation gets a comment.
- **Trilingual or it does not ship.** No citizen-facing string exists in fewer than three
  languages. `sarana_shared.domain.i18n_check` enforces it over `data/seed`.
- **Personal data is absent, not redacted.** Queries that never select a name cannot leak
  one. Seeded households carry no names or phone numbers.

---

## Useful commands

```bash
make up                      # boot everything, migrate, seed
make test                    # full suite
make lint                    # ruff + mypy + eslint + tsc
make seed-generate           # regenerate data/seed
uv run python -m tools.cap_validate artifacts/cap/*.xml
make service-clients                         # provision machine credentials

# gov-mock (file 11)
curl -s localhost:8006/met/v1/warnings | head -1               # XML, with the mock header
curl -X POST localhost:8006/mock/v1/scenario/load  -d '{"scenario_id":"ditwah_kandy"}'
curl -X POST localhost:8006/mock/v1/scenario/advance -d '{"to":"T+6h"}'
curl -X POST localhost:8006/mock/v1/chaos -d '{"timeout_pct":100}'
curl -s localhost:8006/mock/v1/state | jq .clock
open http://localhost:8006/telco/sim                           # the inbound simulator
uv run pytest tests/gov_mock

# agent-svc (file 12)
make eval AGENT=noop                                           # -> artifacts/eval/*.md
uv run python -m agent_svc.runtime.eval --agent noop --fixtures data/fixtures/smoke
uv run pytest tests/agent_svc services/agent-svc/tests
curl -s localhost:8005/api/v1/agents -H "Authorization: Bearer $TOKEN"
curl -s "localhost:8005/api/v1/agents/threads?status=interrupted" -H "Authorization: Bearer $TOKEN"

# forecast agent (file 13)
make eval AGENT=forecast
uv run python -m agent_svc.agents.forecast.replay --scenario ditwah --assert-lead-time 24
uv run python -m tools.seed.ditwah     # regenerate the replay fixture from gov-mock's curve

# warning agent (file 14)
make eval AGENT=warning
uv run python -m tools.sms_segment_check                       # exits 0 over the seed
uv run pytest tests/agents/warning tests/alerting/test_sms_segments.py

# intake agent (file 15)
make eval AGENT=intake
uv run python -m agent_svc.agents.intake.bench --reports 200 --assert-p95 45
uv run pytest tests/agents/intake

# triage agent (file 16)
make eval AGENT=triage
uv run pytest tests/agents/triage/test_gate_cannot_be_bypassed.py
uv run pytest tests/agents/triage

# anomaly agent (file 17)
make eval AGENT=ledger_anomaly       # prints detection AND false-positive per detector
uv run pytest tests/agents/ledger_anomaly

# design system (file 19)
pnpm --filter @sarana/ui test:contrast        # 79 pairings, prints every ratio
pnpm --filter @sarana/ui test:i18n-overflow   # 15 slots x 3 scripts, prints the ratios
pnpm --filter @sarana/ui test:a11y            # axe over all 33 stories
pnpm --filter @sarana/ui test:tokens-sync     # tokens.css/nativewind vs src/tokens
pnpm --filter @sarana/ui tokens:generate      # after editing any token
pnpm --filter @sarana/ui storybook            # localhost:6006, three scripts side by side

# ops console (file 20)
pnpm --filter @sarana/web-ops dev              # http://localhost:3000
pnpm --filter @sarana/web-ops verify-i18n      # 579 keys x si/ta/en, + every key the code uses
pnpm --filter @sarana/web-ops test             # 59 unit
pnpm --filter @sarana/web-ops test:a11y        # axe, 25 screens x 3 locales
pnpm --filter @sarana/web-ops test:e2e         # 93 Playwright, real Chromium
pnpm --filter @sarana/web-ops test:layout      # 24 routes x 3 scripts, overflow only
pnpm --filter @sarana/web-ops build            # 60 static pages; see the Windows EPERM note
pnpm --filter @sarana/web-ops lighthouse -- --assert-js 250   # JS budget, per route, gzipped
SARANA_LIGHTHOUSE_URL=http://localhost:3000/en/ops \
  pnpm --filter @sarana/web-ops lighthouse     # adds the LCP measurement
uv run pytest tests/auth/test_console_scopes.py       # console scopes vs the Scope enum
uv run pytest tests/ledger/test_console_vocabularies.py  # console enums vs the Python ones

# supervisor (file 18)
make eval AGENT=supervisor
uv run pytest tests/agents/supervisor/test_gates_three_layers.py
uv run pytest tests/e2e/test_full_correlation_chain.py
```

`agent:invoke` starts a run; `agent:review` opens the approval inbox and answers an
interrupt. No machine role holds the second one.

Demo accounts and the port map are in [RUNNING.md](RUNNING.md). Password for all of them
is `sarana-demo-passphrase`.
