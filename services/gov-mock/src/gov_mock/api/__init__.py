"""HTTP routes, one module per mocked system.

Each router mounts at the root under the URL shape the real system uses -
`/met/v1/...`, `/ndrsc/v1/...`, `/telco/v1/...` - rather than under a SARANA prefix. See
`gov_mock.main` for why.

`gov_mock.api.deps` holds the two rules every route follows: responses are built with
`mock_json` or `mock_xml` so the mock markers cannot be forgotten, and the current instant
comes from the simulated clock so no route reads the wall clock.
"""
