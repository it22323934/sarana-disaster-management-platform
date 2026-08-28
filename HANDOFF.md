# SARANA — handoff

State of the build as of 2026-08-28. Written for whoever picks this up next.

Read [RUNNING.md](RUNNING.md) first if you have not booted the stack.

---

## Where the build has got to

The repository is organised around 30 numbered build files in `.claude/`. Progress is
strictly sequential and currently sits part-way through 09.

| File | Area | State |
|---|---|---|
| 03 | Monorepo scaffold | Done |
| 04 | Data model | Done |
| 05 | Auth / RBAC | Done |
| 06 | Event backbone | Done |
| 07 | core-api | Done — 29 endpoints |
| 08 | incident-svc | Done — 20 endpoints |
| **09** | **alerting-svc** | **Domain + HTTP done. Targeting is a placeholder.** |
| 10–11 | ledger-svc, gov-mock | Not started |
| 12–18 | Agents (LangGraph) | Not started |
| 19–21 | Web (design system, ops console, public dashboard) | Scaffolds only |
| 22–24 | Mobile (foundation, citizen, field companion) | Scaffold only |
| 25–29 | AWS, observability, security, seed, CI | Not started |
| 30 | Demo script | Not started |

**594 tests passing.** `ruff check`, `ruff format --check` and `mypy` (192 source files)
all clean.

```
core-api        29 endpoints,  6,483 lines
incident-svc    20 endpoints,  4,615 lines
alerting-svc     0 endpoints,  2,028 lines   <- domain only
ledger-svc       0 endpoints,  1,078 lines   <- schema only
agent-svc        0 endpoints,    575 lines   <- schema only
gov-mock         0 endpoints,    172 lines   <- scaffold
```

---

## Start here: finishing file 09

Most of it is done. Three things remain, and the first is load-bearing.

### 1. Real targeting — the one that matters

`alerting_svc.api.v1.alerts._targets_for()` is a **placeholder**. It returns one synthetic
target per GN division so the fan-out, delivery accounting and gaps logic above it are
exercised with the right shape. It does not read a single real household.

Real targeting means reading `admin.household` — `contact_msisdn_hash`,
`preferred_language`, `gn_division_id` — which lives behind core-api and needs the
service-credential flow described below. Until then every delivery number is structurally
correct and factually meaningless.

### 2. The twelve templates are defined but never loaded

`tools/seed/templates.py` holds all twelve, validated by `tests/alerting/
test_seeded_templates.py`. They are **not** wired into `tools/seed/generate.py` or the
manifest, so `make seed` does not create them. Adding that is a few lines — but note they
must load as `DRAFT`, and a human then has to sign each language through
`POST /templates/{id}/review` before anything can be dispatched. That is the gate working,
not an obstacle to route around.

### 3. Coverage endpoint

`GET /api/v1/coverage?gn_division_id=` is not implemented. `SimulatedMesh.coverage()`
already returns modelled reachability per division; it needs a route and the other
channels' equivalents.

### What is done

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

Worked around with `SARANA_INCIDENT_SERVICE_TOKEN`, a long-lived `SERVICE`-role token
minted by `tools/seed/service_token.py` into `.env`.

**This needs a real machine-credential flow before production.** File 07 built
`InternalPrincipalMinter` for the gateway direction only; there is nothing for
downstream→core-api. Consider a client-credentials endpoint on core-api.

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
uv run python tools/seed/service_token.py    # mint a SERVICE token
```

Demo accounts and the port map are in [RUNNING.md](RUNNING.md). Password for all of them
is `sarana-demo-passphrase`.
