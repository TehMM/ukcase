from __future__ import annotations

import logging

from rq import Connection, Worker

from app.workers.jobs import get_redis_connection


def main(queue_name: str = "ukcase") -> None:
    """RQ worker entrypoint."""

    logging.basicConfig(level=logging.INFO)
    connection = get_redis_connection()
    with Connection(connection):
        worker = Worker([queue_name])
        worker.work()
