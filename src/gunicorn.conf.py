"""Gunicorn server hooks."""

from database.sessions import engine


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
