"""Async engine/session construction and the transactional outbox base table.

Domain tables live in each service's own `repo/` — this package only owns what's shared:
the declarative base, timestamp/UUID mixins, session scoping (incl. the RLS session
variable), and the outbox.
"""
