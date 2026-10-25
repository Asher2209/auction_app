"""Phase 2, running MintLot as a real service.

  Worker leases ............ lease_*   (one process at a time runs the background jobs, on any database)
  Separate worker .......... worker_*  (flask run-worker; the web process can leave the jobs to it)
  Shared rate limits ....... redis_*   (the same sliding window in Redis when REDIS_URL is set)
  Behind a proxy ........... proxy_*   (TRUSTED_PROXY_HOPS decides whose address the limits see)
  Health checks ............ health_*  (/healthz alive, /readyz ready to serve)
  Image storage ............ storage_* (on disk, or in an S3-compatible bucket; pages ask upload_url() for addresses)
"""
import importlib.util
import io
from datetime import timedelta
from pathlib import Path

import fakeredis
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from werkzeug.datastructures import FileStorage

from app import create_app, sockets
from app.config import TestConfig
from app.extensions import db
from app.models import Auction, ProductImage, WorkerLease, utcnow
from app.ratelimit import RateLimiter, RedisRateLimiter
from app.services import leases, storage, uploads

from .test_buyer import cats, make_auction  # noqa: F401  (cats is a fixture)
from .test_seller import img_bytes

ROOT = Path(__file__).resolve().parents[1]


# =================================== worker leases ============================================================================
def test_lease_one_holder_at_a_time_and_renewals_keep_it(app):
    now = utcnow()
    assert leases.acquire("job", "a", 30, now) is True
    assert leases.acquire("job", "b", 30, now + timedelta(seconds=5)) is False  # a still holds it
    assert leases.acquire("job", "a", 30, now + timedelta(seconds=20)) is True  # a renews
    assert leases.acquire("job", "b", 30, now + timedelta(seconds=40)) is False  # renewed until 50s
    assert db.session.get(WorkerLease, "job").holder == "a"


def test_lease_passes_on_when_the_holder_stops_renewing(app):
    now = utcnow()
    leases.acquire("job", "a", 30, now)
    assert leases.acquire("job", "b", 30, now + timedelta(seconds=31)) is True
    assert leases.acquire("job", "a", 30, now + timedelta(seconds=32)) is False
    assert db.session.get(WorkerLease, "job").holder == "b"


def test_lease_released_early_is_free_at_once(app):
    leases.acquire("job", "a", 300)
    leases.release("job", "a")
    assert leases.acquire("job", "b", 300) is True
    leases.release("job", "a")  # releasing someone else's lease does nothing
    assert leases.acquire("job", "a", 300) is False


def test_lease_different_jobs_do_not_block_each_other(app):
    assert leases.acquire("one", "a", 30) and leases.acquire("two", "b", 30)


def test_lease_holder_ids_differ_per_process_even_on_one_host():
    assert leases.holder_id() != leases.holder_id()


MIGRATION = ROOT / "migrations" / "versions" / "p26leases01_worker_leases.py"


def test_lease_the_migration_creates_and_drops_the_table():
    spec = importlib.util.spec_from_file_location("p26", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
        assert {c["name"] for c in sa.inspect(conn).get_columns("worker_leases")} == {"name", "holder", "expires_at"}
        with Operations.context(MigrationContext.configure(conn)):
            module.downgrade()
        assert "worker_leases" not in sa.inspect(conn).get_table_names()


# =================================== separate worker ==========================================================================
def test_worker_a_tick_closes_finished_auctions_only_for_the_lease_holder(app, users, cats):  # noqa: F811
    a = make_auction(users["seller"], cats["Books"], "Done", 100)
    a.end_time = utcnow() - timedelta(seconds=1)
    db.session.commit()
    leases.acquire(sockets.LEASE, "someone-else", 60)
    assert sockets.scheduler_tick(app, "me") is False
    assert db.session.get(Auction, a.id).status == "active"  # the other worker's job
    leases.release(sockets.LEASE, "someone-else")
    assert sockets.scheduler_tick(app, "me") is True
    db.session.expire_all()
    assert db.session.get(Auction, a.id).status == "closed"


def test_worker_command_runs_one_tick_and_hands_the_lease_back(app):
    result = app.test_cli_runner().invoke(args=["run-worker", "--once"])
    assert result.exit_code == 0 and "worked" in result.output and "stopped" in result.output
    lease = db.session.get(WorkerLease, sockets.LEASE)
    assert lease is not None and lease.expires_at <= utcnow()  # released, so the next worker need not wait


def test_worker_command_stands_by_while_another_worker_holds_the_lease(app):
    leases.acquire(sockets.LEASE, "the-active-worker", 60)
    result = app.test_cli_runner().invoke(args=["run-worker", "--once"])
    assert result.exit_code == 0 and "standing by" in result.output
    assert db.session.get(WorkerLease, sockets.LEASE).holder == "the-active-worker"


def test_worker_lease_outlives_a_slow_tick():
    class Cfg:
        config = {"SCHEDULER_INTERVAL_SECONDS": 5}
    assert sockets.lease_seconds(Cfg) >= 15


# =================================== shared rate limits =======================================================================
class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def redis_limiter(app):
    clock = Clock()
    return RedisRateLimiter(fakeredis.FakeRedis(), clock=clock), clock


def test_redis_counts_a_sliding_window_like_the_in_memory_limiter(redis_limiter):
    shared, clock = redis_limiter
    local_clock = Clock(clock.t)
    local = RateLimiter(clock=local_clock)
    for limiter in (shared, local):
        for _ in range(3):
            limiter.hit("k", 60)
    for step in (0, 30, 59, 61):
        clock.t = local_clock.t = 1_000_000.0 + step
        assert shared.count("k", 60) == local.count("k", 60), step
        assert shared.retry_after("k", 3, 60) == local.retry_after("k", 3, 60), step


def test_redis_retry_after_waits_for_the_hit_that_matters(redis_limiter):
    limiter, clock = redis_limiter
    for offset in (0, 10, 20):
        clock.t = 1_000_000.0 + offset
        limiter.hit("login", 60)
    clock.t = 1_000_000.0 + 25
    assert limiter.retry_after("login", 3, 60) == 36  # the first hit leaves the window at 60s
    assert limiter.retry_after("login", 4, 60) == 0


def test_redis_clear_forgets_a_key_and_keys_expire_on_their_own(redis_limiter):
    limiter, _ = redis_limiter
    limiter.hit("a", 60)
    limiter.clear("a")
    assert limiter.count("a", 60) == 0
    limiter.hit("b", 60)
    assert 0 < limiter._r.ttl(RedisRateLimiter.PREFIX + "b") <= 61


def test_redis_an_outage_lets_requests_through_and_is_logged(app, caplog):
    class Down:
        def __getattr__(self, name):
            def fail(*a, **k):
                raise ConnectionError("redis is down")
            return fail
    limiter = RedisRateLimiter(Down())
    limiter.hit("x", 60)
    assert limiter.count("x", 60) == 0 and limiter.retry_after("x", 1, 60) == 0
    assert "Redis is unavailable" in caplog.text


def test_redis_the_app_counts_in_redis_when_redis_url_is_set(monkeypatch, tmp_path):
    import redis
    monkeypatch.setattr(redis.Redis, "from_url", classmethod(lambda cls, url, **kw: fakeredis.FakeRedis()))

    class WithRedis(TestConfig):
        REDIS_URL = "redis://redis.example:6379/0"

    app = create_app(WithRedis)
    assert isinstance(app.extensions["limiter"], RedisRateLimiter)
    assert isinstance(create_app(TestConfig).extensions["limiter"], RateLimiter)


# =================================== behind a proxy ===========================================================================
def proxied_app(hops):
    class Cfg(TestConfig):
        TRUSTED_PROXY_HOPS = hops

    app = create_app(Cfg)

    @app.route("/_who")
    def who():
        from flask import request
        from app.ratelimit import client_ip
        return {"ip": client_ip(), "scheme": request.scheme}
    return app


def test_proxy_headers_are_ignored_unless_a_proxy_is_trusted():
    r = proxied_app(0).test_client().get("/_who", headers={"X-Forwarded-For": "6.6.6.6", "X-Forwarded-Proto": "https"})
    assert r.json == {"ip": "127.0.0.1", "scheme": "http"}  # nobody can pick their own address


def test_proxy_one_trusted_hop_gives_the_visitors_address_not_the_proxys():
    r = proxied_app(1).test_client().get("/_who", headers={"X-Forwarded-For": "6.6.6.6, 203.0.113.7", "X-Forwarded-Proto": "https"})
    assert r.json == {"ip": "203.0.113.7", "scheme": "https"}  # only the hop our own proxy added counts


# =================================== health checks ============================================================================
def test_health_alive_and_ready(client):
    assert client.get("/healthz").json == {"status": "ok"}
    r = client.get("/readyz")
    assert r.status_code == 200 and r.json == {"status": "ok", "checks": {"database": "ok"}}
    assert client.get("/health").json == {"status": "ok"}  # the older probe still answers


def test_health_not_ready_when_the_database_fails(client, monkeypatch):
    def broken(*a, **k):
        raise sa.exc.OperationalError("SELECT 1", {}, Exception("database is gone"))
    monkeypatch.setattr(db.session, "execute", broken)
    r = client.get("/readyz")
    assert r.status_code == 503 and r.json["checks"]["database"] == "failing"


def test_health_checks_redis_when_it_is_configured(app, client):
    app.config["REDIS_URL"] = "redis://redis.example:6379/0"
    app.extensions["limiter"] = RedisRateLimiter(fakeredis.FakeRedis())
    assert client.get("/readyz").json["checks"] == {"database": "ok", "redis": "ok"}
    server = fakeredis.FakeServer()
    server.connected = False
    app.extensions["limiter"] = RedisRateLimiter(fakeredis.FakeRedis(server=server))
    r = client.get("/readyz")
    assert r.status_code == 503 and r.json["checks"]["redis"] == "failing"


def test_health_replies_say_nothing_secret(client):
    body = client.get("/readyz").get_data(as_text=True)
    assert "sqlite" not in body.lower() and "password" not in body.lower()


# =================================== image storage ============================================================================
class FakeS3:
    """Stands in for boto3's S3 client: records what was stored and deleted."""
    def __init__(self, fail=False):
        self.objects, self.deleted, self.fail = {}, [], fail

    def upload_fileobj(self, fileobj, bucket, key, ExtraArgs):  # noqa: N803  (boto3's argument name)
        if self.fail:
            raise OSError("bucket unreachable")
        self.objects[(bucket, key)] = (fileobj.read(), ExtraArgs)

    def delete_object(self, Bucket, Key):  # noqa: N803
        self.deleted.append((Bucket, Key))


def bucket(app, fail=False):
    store = storage.S3Storage.__new__(storage.S3Storage)  # skip boto3 setup: the fake client goes in instead
    store.bucket, store.public_base_url, store.client = "cards", "https://images.mintlot.example", FakeS3(fail)
    app.extensions["storage"] = store
    return store


def test_storage_local_saves_under_the_upload_folder_and_serves_from_static(app):
    store = storage.backend()
    store.save(io.BytesIO(b"png bytes"), "products/abc.png", "image/png")
    assert (Path(app.config["UPLOAD_FOLDER"]) / "products" / "abc.png").read_bytes() == b"png bytes"
    with app.test_request_context():
        assert storage.upload_url("products/abc.png") == "/static/uploads/products/abc.png"
    store.delete("products/abc.png")
    assert not (Path(app.config["UPLOAD_FOLDER"]) / "products" / "abc.png").exists()


def test_storage_local_never_writes_outside_the_upload_folder(app):
    with pytest.raises(storage.StorageError):
        storage.backend().save(io.BytesIO(b"x"), "../../escape.txt", "text/plain")
    storage.backend().delete("../../../run.py")  # a bad key is ignored, not followed
    assert (ROOT / "run.py").exists()


def test_storage_uploads_go_to_the_bucket_with_their_type_and_a_long_cache(app):
    store = bucket(app)
    with app.test_request_context():
        keys = uploads.save_images([FileStorage(img_bytes(), "front.png")])
        (key,) = keys
        assert key.startswith("products/") and key.endswith(".png")
        data, extra = store.client.objects[("cards", key)]
        assert data.startswith(b"\x89PNG") and extra["ContentType"] == "image/png" and "immutable" in extra["CacheControl"]
        assert storage.upload_url(key) == f"https://images.mintlot.example/{key}"
        uploads.delete_files(keys)
    assert store.client.deleted == [("cards", key)]


def test_storage_a_bucket_failure_is_a_clean_upload_error(app):
    bucket(app, fail=True)
    with app.test_request_context(), pytest.raises(uploads.UploadError):
        uploads.save_images([FileStorage(img_bytes(), "front.png")])


def test_storage_pages_show_bucket_addresses_for_card_images(app, client, users, cats):  # noqa: F811
    bucket(app)
    a = make_auction(users["seller"], cats["Books"], "Lamp", 100)
    a.product.images.append(ProductImage(path="products/lamp.png"))
    db.session.commit()
    html = client.get(f"/auctions/{a.id}").get_data(as_text=True)
    assert "https://images.mintlot.example/products/lamp.png" in html and "/static/uploads/products/lamp.png" not in html
    tiles = client.get("/auctions/").get_data(as_text=True)  # drawn by an imported macro, which needs a real Jinja global
    assert f"https://images.mintlot.example/{a.product.cover}" in tiles and "/static/uploads/" not in tiles


def test_storage_s3_refuses_to_start_half_configured():
    class Half(TestConfig):
        STORAGE_BACKEND = "s3"
        S3_BUCKET = "cards"
    with pytest.raises(RuntimeError, match="S3_PUBLIC_BASE_URL"):
        create_app(Half)


def test_storage_no_template_builds_upload_addresses_by_hand():
    for f in (ROOT / "app" / "templates").rglob("*.html"):
        text = f.read_text(encoding="utf-8")
        assert "filename='uploads/" not in text and 'filename="uploads/' not in text, f.name  # use upload_url()


# =================================== migrations match the models ==============================================================
def test_schema_built_by_every_migration_is_exactly_what_the_models_describe(tmp_path, monkeypatch):
    """The whole chain on an empty SQLite file, then a comparison with the models: no table, column, type or index may
    differ (CI does the same on PostgreSQL with `flask db check`)."""
    from alembic.autogenerate import compare_metadata
    from flask_migrate import downgrade, upgrade

    class Fresh(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'fresh.db'}"

    app = create_app(Fresh)
    with app.app_context():
        upgrade(directory=str(ROOT / "migrations"))
        with db.engine.connect() as conn:
            differences = compare_metadata(MigrationContext.configure(conn), db.metadata)
        assert differences == []
        downgrade(directory=str(ROOT / "migrations"), revision="base")  # and every step comes back down
        assert set(sa.inspect(db.engine).get_table_names()) <= {"alembic_version"}
        db.engine.dispose()
