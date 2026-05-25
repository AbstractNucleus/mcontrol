"""Business-logic services between routes and db/docker_client.

Route handlers parse input and render responses; services own the rules.
Services import from ``db_async``, ``docker_client``, ``lifecycle_state``
etc.. the same dependencies the routes used to call directly. and are
deliberately FastAPI-unaware (no ``Request``, no ``HTMLResponse``, no
HTMX headers). Each function takes primitives or domain dicts and
returns primitives or domain dicts; errors propagate as plain
exceptions the route layer translates into HTTP responses.
"""
