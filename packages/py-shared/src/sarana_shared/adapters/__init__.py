"""Clients for systems SARANA does not own.

One subpackage per family of external system. Nothing here talks to a SARANA service -
those calls live in the calling service's own `adapters/` package, because they are that
service's business and not a shared contract.
"""
