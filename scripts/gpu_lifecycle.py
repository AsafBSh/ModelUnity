"""Serialize GPU operations and release owned engines, including failed loads."""

from contextvars import ContextVar
from functools import wraps
from threading import RLock

_owned = ContextVar("modelunify_gpu_owners", default=None)
_lock = RLock()


def register(resource):
    owners = _owned.get()
    if owners is not None:
        owners.append(resource)


def operation(*resources):
    def decorate(fn):
        @wraps(fn)
        def run(*args, **kwargs):
            with _lock:
                owners = list(resources)
                token = _owned.set(owners)
                try:
                    return fn(*args, **kwargs)
                finally:
                    try:
                        for resource in reversed(owners):
                            try:
                                resource.unload()
                            except Exception as exc:
                                print(
                                    f"[GPU] Cleanup failed for {type(resource).__name__}: {exc}"
                                )
                    finally:
                        _owned.reset(token)

        return run

    return decorate
