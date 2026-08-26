"""agent-svc — the six SARANA agents (Forecast & Impact, Warning Dissemination, Intake
& Verification, Triage & Dispatch, Aid Ledger & Anomaly, Supervisor/Orchestrator) on the
shared LangGraph runtime.

See docs/build-prompts/12-langgraph-runtime.md (build first) and 13-18 (one agent each)
for the full spec. This scaffold only provides the FastAPI app factory, config, and
health/readiness endpoints — no runtime, no agents, no LLM calls yet.
"""
