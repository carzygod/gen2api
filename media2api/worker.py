from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import signal
import time
from typing import Any

from .catalog import seed_defaults
from .config import settings
from .database import SessionLocal, init_db
from .services_core import JobRuntime


running = True


def stop(signum, frame) -> None:
    global running
    running = False


def log_event(event: str, **fields: Any) -> None:
    payload = {"event": event, "ts": int(time.time()), **fields}
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def run_once(runtime: JobRuntime) -> bool:
    with SessionLocal() as db:
        recovered = runtime.recover_stalled_jobs(db)
        expired = runtime.sweep_expired_leases(db)
        job = runtime.next_queued_job(db)
        if not job:
            return bool(recovered.get("recovered")) or expired > 0
        runtime.process_job(db, job.id)
        return True


def worker_loop(worker_id: int) -> None:
    runtime = JobRuntime()
    log_event("worker_started", worker_id=worker_id)
    while running:
        try:
            did_work = run_once(runtime)
        except Exception as exc:
            log_event("worker_error", worker_id=worker_id, error=type(exc).__name__, message=str(exc))
            time.sleep(settings.worker_poll_interval_seconds)
            continue
        if not did_work:
            time.sleep(settings.worker_poll_interval_seconds)
    log_event("worker_stopped", worker_id=worker_id)


def main() -> None:
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    init_db()
    with SessionLocal() as db:
        seed_defaults(db)
    concurrency = max(1, settings.worker_concurrency)
    log_event("worker_pool_started", concurrency=concurrency, poll_interval_seconds=settings.worker_poll_interval_seconds)
    if concurrency == 1:
        worker_loop(0)
        return
    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="media2api-worker") as executor:
        futures = [executor.submit(worker_loop, index) for index in range(concurrency)]
        while running:
            for index, future in enumerate(futures):
                if future.done():
                    exc = future.exception()
                    if exc:
                        log_event("worker_thread_exited", worker_id=index, error=type(exc).__name__, message=str(exc))
                    futures[index] = executor.submit(worker_loop, index)
            time.sleep(0.5)


if __name__ == "__main__":
    main()
