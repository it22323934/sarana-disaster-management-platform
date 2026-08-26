"""gov-mock — every Sri Lankan government and telco system SARANA integrates with,
mocked with a realistic contract, latency, and failure behaviour.

See docs/build-prompts/11-gov-mock-services.md for the full service spec (Dept. of
Meteorology, NBRO, DMC, NDRSC, GN/household registry, payment rail, telco SMS/USSD, and
the scenario driver). This scaffold only provides the FastAPI app factory, config, and
health/readiness endpoints.
"""
