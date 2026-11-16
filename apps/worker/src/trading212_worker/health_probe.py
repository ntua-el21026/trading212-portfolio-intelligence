"""Collect one worker ping reply within the existing Docker health budget."""

from __future__ import annotations


def main() -> int:
    # Import the worker's real application; its configuration and task registration
    # remain identical to the consumer. Do not create a separate broker client.
    try:
        from trading212_worker.tasks import celery_app

        if celery_app is None:
            return 1
        replies = celery_app.control.inspect(timeout=5, limit=1).ping()
    except Exception:
        # Health output must not disclose replies, configuration or exceptions.
        return 1
    if not isinstance(replies, dict):
        return 1
    return (
        0
        if any(isinstance(reply, dict) and reply.get("ok") == "pong" for reply in replies.values())
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
