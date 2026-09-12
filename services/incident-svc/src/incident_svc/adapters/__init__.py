"""Outbound adapters for incident-svc: HTTP clients, event bus, object storage.

Everything that leaves the process goes through an adapter, so a test can substitute one
without a network.
"""
