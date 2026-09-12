"""Service-to-service endpoints, mounted outside `/api/v1`.

Nothing here is reachable with a citizen's or an officer's bearer token by design: the
audit write path in particular must not sit on the surface a browser can reach.
"""
