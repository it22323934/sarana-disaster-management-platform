"""Shared domain types: admin hierarchy, localisation, money, geo, ids, and time.

Pure types and pure functions only — no I/O, no database, no HTTP. Every service depends
on this module; it depends on nothing service-specific (docs/build-prompts/02-conventions.md:
"Dependencies point inward.").
"""
