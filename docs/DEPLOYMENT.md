# Deploying MintLot

This is how MintLot runs as a real service. Everything described here exists in the repository and is checked by CI;
anything not built yet is listed at the end.

## The pieces

| Piece | What it is | Notes |
| --- | --- | --- |
| **web** | The Docker image running gunicorn (`deployment/gunicorn.conf.py`) | One process, many threads (Socket.IO keeps its connections in the process). Scale by running more containers. |
| **worker** | The same image running `flask run-worker` | Starts and closes auctions, settles simulated payments, confirms blockchain payments and mints. A lease in the database lets only one worker work at a time; a second one stands by and takes over within ~15 s if the first stops. |
| **database** | PostgreSQL 16 or 17 | The schema comes only from `flask db upgrade`. Production refuses to start on SQLite. |
| **Redis** | Any Redis 6+ | Needed as soon as there is more than one process: live bid updates reach every browser, rate limits are counted once. Without it, everything still works in a single process. |
| **image storage** | Local disk or an S3-compatible bucket | A container's disk is lost when it is replaced, so hosted sites should use a bucket (`STORAGE_BACKEND=s3`). |
| **email** | Any SMTP service | Without `MAIL_SERVER` emails are only written to the log. |
| **error reports** | Sentry (optional) | Off unless `SENTRY_DSN` is set. No cookies, IP addresses or user details are sent. |

Browsers connect to Socket.IO by WebSocket only (no long-polling fallback), so a load balancer does **not** need sticky
sessions. Every current browser supports WebSockets; a network that blocks them only loses the live updates, and pages
still show the right state when reloaded.

## Run the whole stack locally

Needs Docker Desktop (on Windows, with an up-to-date WSL).

```
docker compose up --build
```

Then open http://localhost:8000. Compose starts Postgres, Redis, a one-off `migrate` container (`flask db upgrade`),
the web container on port 8000 and the worker. Secrets are read from your `.env`; the database and Redis settings in
`compose.yaml` win. The database lives in the `pgdata` volume:

```
docker compose down          # stop, keep the data
docker compose down -v       # stop and delete the data
docker compose logs -f web worker
```

To load the demo accounts and cards into the Compose database: `docker compose run --rm web python scripts/seed.py`.

## Health checks

| Path | Answers | Use it for |
| --- | --- | --- |
| `/healthz` | `{"status": "ok"}` whenever the process runs | Liveness: restart the container if it fails |
| `/readyz` | 200 with `{"checks": {"database": "ok", "redis": "ok"}}`, or 503 naming what fails | Readiness: send traffic only while it is 200 |

The blockchain RPC is deliberately not part of `/readyz`: a slow provider must not take the whole site out of service.
The image's own `HEALTHCHECK` calls `/healthz`.

## Production settings

`APP_ENV=production` makes the app refuse to start until these are right (see `security.production_problems`):

- `SECRET_KEY`: a random value of 32+ characters (`python -c "import secrets; print(secrets.token_hex(32))"`)
- `SECURE_COOKIES=1` and `APP_BASE_URL=https://...`: the site is served over HTTPS
- `ALLOW_TEST_EMAILS=0`, `LOCAL_CHAIN` unset
- `DATABASE_URL=postgresql+psycopg://user:password@host:5432/dbname`

Set as well:

| Setting | Value |
| --- | --- |
| `ENABLE_SCHEDULER` | `0` on web containers when a worker runs (the default `1` runs the jobs inside the web process, which suits a single-container setup) |
| `REDIS_URL` | e.g. `rediss://default:password@host:6379` (needed with more than one container) |
| `TRUSTED_PROXY_HOPS` | `1` behind one load balancer or platform router, so rate limits see the visitor's address and not the proxy's. Leave `0` when nothing sits in front: then nobody can fake their address. |
| `STORAGE_BACKEND=s3`, `S3_*` | see `.env.example` |
| `MAIL_SERVER`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_DEFAULT_SENDER` | your SMTP service |
| `SENTRY_DSN` | optional |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | optional; add `<APP_BASE_URL>/auth/google/callback` to the Google client's redirect URIs |
| `RPC_URL`, `CONTRACT_ADDRESS`, `COLLECTIBLE_CONTRACT_ADDRESS` | for blockchain payments and card tokens (test network only) |

`deployment/production.env.example` lists them all in one place.

## Releasing a new version

1. Build and push the image (`docker build -t <registry>/mintlot:<version> .`).
2. Run `flask db upgrade` once with the new image (Compose does this with the `migrate` service; on a platform, as a
   release or pre-deploy command). It does nothing when the schema is already current, and every migration has a downgrade.
3. Replace the web and worker containers. Logins survive: sessions are signed cookies plus a row in `user_sessions`.

Rolling back: deploy the previous image; run `flask db downgrade <revision>` only if the new version's migration must
be undone (most can stay, as older code ignores new columns).

## Backups

Use the database provider's automatic backups, or `pg_dump --format=custom "$DATABASE_URL" > mintlot.dump` on a
schedule. Images in a bucket should have versioning or the provider's backup turned on. Test a restore before relying
on either.

## Not built yet

- No hosting is set up: choosing a provider is the paid step left for the end of the upgrade plan.
- No staging environment, no metrics endpoint, no alerting beyond Sentry.
- Load has been tested only with `deployment/load_test.py` against a single local process.
