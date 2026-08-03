"""Gunicorn server hooks."""

from database.sessions import engine

# gunicorn's default worker silence timeout (30s) is shorter than the SQLite
# busy-timeout configured in database/sessions.py (connect_args={"timeout": 60}).
# While app.py's cache-prewarm threads are still writing to the DB in the
# master, a worker's first real query can legitimately block inside SQLite's
# busy-wait for up to 60s — longer than gunicorn is willing to wait, so it
# kills the worker mid-wait even though nothing is actually stuck. Raising
# gunicorn's own timeout above that ceiling lets it wait out a slow-but-valid
# first response instead of misdiagnosing it as a hung worker.
timeout = 90


def post_fork(server, worker):
    """Reset the DB connection pool inherited from the preloaded master.

    --preload forks after app.py already opened connections (via the
    cache-prewarm threads), so a worker can inherit the pool mid-connect,
    including a SQLAlchemy-internal lock left permanently acquired by a
    thread that no longer exists post-fork. Disposing recreates the pool
    (and its locks) cleanly in each worker; it does not affect the
    in-process caches that --preload is meant to share via copy-on-write.
    """
    engine.dispose()
