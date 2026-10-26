# Superseded deployment material (archived October 2026)

Kept for the record only; none of it describes how MintLot is deployed now. It assumed one hand-built server running
the app straight from a checkout, with SQLite copied by shell scripts, and it described health and metrics endpoints
(`/api/health/*`, `/api/metrics`, `/admin/metrics`) that the app never had. `migrate.py` was an empty placeholder.

The current way is in [docs/DEPLOYMENT.md](../../DEPLOYMENT.md): a Docker image, Postgres, Redis, a separate worker,
`flask db upgrade` for the schema and `/healthz` and `/readyz` for the platform.
