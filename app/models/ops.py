from ..extensions import db


class WorkerLease(db.Model):
    """Who may run a background job right now (services/leases.py): one row per job, held until expires_at."""
    __tablename__ = "worker_leases"

    name = db.Column(db.String(64), primary_key=True)
    holder = db.Column(db.String(128), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
