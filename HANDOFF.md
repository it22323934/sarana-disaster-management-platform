# SARANA — handoff

State of the build as of 2026-08-29. Written for whoever picks this up next.

Read [RUNNING.md](RUNNING.md) first if you have not booted the stack.

---

## Where the build has got to

The repository is organised around 30 numbered build files in `.claude/`. Progress is
strictly sequential. Files 03-11 are complete; the next unstarted file is 12.

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
| 11 | gov-mock | Done — 35 endpoints, 7 mocked systems, inbound simulator |
| **12** | **LangGraph runtime** | **Not started — start here** |
| 13–18 | Agents | Not started |
| 19–21 | Web (design system, ops console, public dashboard) | Scaffolds only |
| 22–24 | Mobile (foundation, citizen, field companion) | Scaffold only |
| 25–29 | AWS, observability, security, seed, CI | Not started |
| 30 | Demo script | Not started |

**1,066 tests passing, 2 skipped.** `ruff check`, `ruff format --check` and `mypy` (261
source files) all clean.

```
core-api        29 endpoints,  6,483 lines
incident-svc    20 endpoints,  4,615 lines
alerting-svc    15 endpoints,  3,357 lines
ledger-svc      29 endpoints,  6,900 lines
gov-mock        35 endpoints,  4,900 lines   <- 7 mocked systems + control plane
agent-svc        0 endpoints,    575 lines   <- schema only
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
  role. incident-svc holds `admin:read` and nothing else; alerting-svc is the only
  credential in the platform with `household:contact_read`; gov-mock's gateway holds
  `incident:write` and cannot read anything.
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
- **Agent seams** — `incident_svc.domain.dispatch_gate.NullResumer` stands in for the
  LangGraph runtime. Every safety property of the gate holds without it; the response
  reports `graph_resumed: false` so nothing mistakes it for a completed agent decision.
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
```

Demo accounts and the port map are in [RUNNING.md](RUNNING.md). Password for all of them
is `sarana-demo-passphrase`.
