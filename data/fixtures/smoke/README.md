# Smoke fixtures

The smallest labelled set that exercises an agent end to end. Ten cases, no model provider,
no network — enough to prove the runtime works and to catch a regression in a graph's
routing, and small enough that CI runs it on every push.

```bash
python -m agent_svc.runtime.eval --agent noop --fixtures data/fixtures/smoke
make eval AGENT=noop
```

The real evaluation set — hundreds of labelled reports across the three languages, with the
calibration curve that means anything — is file 28. This is not that. Passing here means the
plumbing is intact, not that an agent is good.

## Case format

One JSON object per line:

| Field | Meaning |
| --- | --- |
| `id` | Names the case in the report. Make it say what the case is about. |
| `subject_id` | The thread id is derived from it, so it must be unique in the file. |
| `input` | What the run starts with. |
| `label` | The expected output fields. Only these are judged; anything else the agent emits is ignored. |
| `expect_human_review` | Whether the agent *should* stop and ask. Scored separately from accuracy — a gate that fires on the wrong cases is a distinct failure from a wrong answer. |
| `human` | The decision to give when it does stop. Without it the reviewed path is the part nobody measures. |

## Writing cases

Label what the right answer is, not what the agent currently says. A fixture set edited to
match a regression is a test suite that has stopped testing.

Include the cases the agent gets wrong. `no-hazard-word` describes a landslide without using
the word, and the deterministic classifier cannot place it — that case is in here precisely
because it is the one that has to route to a person, and an eval set with only easy cases
reports a calibration curve that means nothing.
