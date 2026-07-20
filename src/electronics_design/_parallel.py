"""Shared bounded parallelism configuration."""

from __future__ import annotations

import os
from typing import Mapping
from typing import Optional


_PARALLEL_WORKERS_ENV = "ELECTRONICS_DESIGN_PARALLEL_WORKERS"
_DEFAULT_WORKER_CAP = 8
_configured_worker_count: Optional[int] = None


def parallel_worker_count(task_count: Optional[int] = None) -> int:
    """Return a bounded worker count, optionally limited by task count."""

    available_cpus = os.cpu_count() or 1
    if _configured_worker_count is not None:
        worker_count = min(_configured_worker_count, available_cpus)
    else:
        raw_worker_count = os.environ.get(_PARALLEL_WORKERS_ENV, "").strip()
        if raw_worker_count == "":
            worker_count = min(available_cpus, _DEFAULT_WORKER_CAP)
        else:
            try:
                worker_count = int(raw_worker_count)
            except ValueError:
                worker_count = min(available_cpus, _DEFAULT_WORKER_CAP)
            worker_count = max(1, min(worker_count, available_cpus))
    if task_count is not None:
        worker_count = min(worker_count, max(1, int(task_count)))
    return worker_count


def configure_parallel_workers(convert_settings: Mapping[str, object]) -> bool:
    """Apply a validated per-conversion worker override to pools and Numba."""

    global _configured_worker_count
    raw_worker_count = convert_settings.get("parallel_workers")
    if raw_worker_count is None:
        _configured_worker_count = None
    elif isinstance(raw_worker_count, bool):
        return False
    else:
        try:
            requested_worker_count = int(raw_worker_count)
        except (TypeError, ValueError):
            return False
        if requested_worker_count <= 0:
            return False
        _configured_worker_count = requested_worker_count
    try:
        from numba import set_num_threads

        set_num_threads(parallel_worker_count())
    except (ImportError, ValueError):
        return False
    return True
