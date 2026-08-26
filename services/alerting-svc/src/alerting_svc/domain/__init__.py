"""Pure business logic for alerting-svc.

No I/O lives here: no database session, no HTTP client, no event bus. Everything in this
package is a function of its arguments, which is what makes it testable without a
container and reviewable without tracing a call chain.
"""
