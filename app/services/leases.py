"""Leases: at most one process runs a background job at a time, whichever database is behind the app.

A lease is a row naming the job, who holds it and until when. Taking or renewing it is a single conditional UPDATE
("mine, or nobody's, or expired"), so two processes racing for it cannot both win; the very first take is an INSERT,
which the primary key settles the same way. A holder that dies simply stops renewing, and the lease passes on once
it expires. Nothing here needs Redis or database-specific locks.
"""
import os
import socket
import uuid
from datetime import timedelta

from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import WorkerLease, utcnow


def holder_id():
    """Unique per process: host, process id and a random tail (process ids are reused across containers)."""
    return f"{socket.gethostname()[:60]}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def acquire(name, holder, ttl_seconds, now=None):
    """Take or renew the lease `name` for `holder`. True if `holder` now holds it until now + ttl."""
    now = now or utcnow()
    until = now + timedelta(seconds=ttl_seconds)
    claimed = db.session.execute(
        update(WorkerLease)
        .where(WorkerLease.name == name, or_(WorkerLease.holder == holder, WorkerLease.expires_at <= now))
        .values(holder=holder, expires_at=until),
        execution_options={"synchronize_session": False}).rowcount
    if claimed:
        db.session.commit()
        return True
    if db.session.get(WorkerLease, name) is not None:  # someone else holds it and it has not expired
        db.session.rollback()
        return False
    db.session.add(WorkerLease(name=name, holder=holder, expires_at=until))
    try:
        db.session.commit()
        return True
    except IntegrityError:  # another process inserted it first
        db.session.rollback()
        return False


def release(name, holder):
    """Give the lease up early (on a clean shutdown) so the next worker need not wait for it to expire."""
    db.session.execute(
        update(WorkerLease).where(WorkerLease.name == name, WorkerLease.holder == holder).values(expires_at=utcnow()),
        execution_options={"synchronize_session": False})
    db.session.commit()
