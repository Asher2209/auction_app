"""Command-line entry points (flask --app run.py <command>)."""
import signal
import time

import click

from . import sockets
from .services import leases


def init_app(app):
    @app.cli.command("run-worker")
    @click.option("--once", is_flag=True, help="Run a single tick and exit (for cron or a health probe).")
    def run_worker(once):
        """Run the background jobs (start and close auctions, confirm blockchain payments and mints) in their own process.

        Start the web servers with ENABLE_SCHEDULER=0 and run one or more of these. A lease in the database makes sure
        only one of them works at a time; the others wait and take over if it stops. With REDIS_URL set, the "auction
        closed" announcements reach browsers through Redis; without it they are only logged.
        """
        holder = leases.holder_id()
        interval = app.config["SCHEDULER_INTERVAL_SECONDS"]
        if not app.config.get("REDIS_URL"):
            app.logger.warning("REDIS_URL is not set: this worker cannot send live updates to browsers.")
        stopping = []
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stopping.append(True))
        click.echo(f"MintLot worker {holder} started (tick every {interval}s).")
        try:
            while not stopping:
                try:
                    worked = sockets.scheduler_tick(app, holder)
                except Exception:  # keep running; a bad tick must not stop the worker
                    app.logger.exception("Worker tick failed")
                    worked = None
                if once:
                    click.echo("worked" if worked else "standing by: another worker holds the lease" if worked is False else "failed")
                    return
                for _ in range(interval * 10):  # sleep in small steps so a stop signal is noticed quickly
                    if stopping:
                        break
                    time.sleep(0.1)
        finally:
            with app.app_context():
                leases.release(sockets.LEASE, holder)
            click.echo("MintLot worker stopped.")
