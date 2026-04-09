"""Retry policy utilities for asynchronous and synchronous call sites."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar

import httpx
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.core.logging import get_logger

_AsyncFunc = TypeVar("_AsyncFunc", bound=Callable[..., Awaitable[Any]])
_SyncFunc = TypeVar("_SyncFunc", bound=Callable[..., Any])


def _logger():
    """Return the module logger lazily to avoid early settings evaluation."""

    return get_logger(__name__)


def _is_retryable_exception(exc: BaseException) -> bool:
    """Return True when an exception should trigger a retry."""

    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    if isinstance(exc, httpx.NetworkError | ConnectionError):
        return True
    return False


def _log_before_sleep(retry_state: RetryCallState) -> None:
    """Emit a warning before tenacity sleeps for the next retry."""

    if retry_state.fn is None:
        function_name = "unknown"
    else:
        function_name = retry_state.fn.__name__

    _logger().warning(
        "Retrying function after failure.",
        extra={
            "function": function_name,
            "attempt": retry_state.attempt_number,
        },
    )


def _get_wait_strategy() -> Any:
    """Build the wait strategy used by retry wrappers."""

    return wait_exponential(multiplier=1, min=2, max=30)


def with_retry(func: _AsyncFunc) -> _AsyncFunc:
    """Wrap an async function with the platform retry policy."""

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        async for attempt in AsyncRetrying(
            reraise=True,
            stop=stop_after_attempt(3),
            wait=_get_wait_strategy(),
            retry=retry_if_exception(_is_retryable_exception),
            before_sleep=_log_before_sleep,
        ):
            with attempt:
                return await func(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


def with_retry_sync(func: _SyncFunc) -> _SyncFunc:
    """Wrap a synchronous function with the platform retry policy."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        for attempt in Retrying(
            reraise=True,
            stop=stop_after_attempt(3),
            wait=_get_wait_strategy(),
            retry=retry_if_exception(_is_retryable_exception),
            before_sleep=_log_before_sleep,
        ):
            with attempt:
                return func(*args, **kwargs)

    return wrapper  # type: ignore[return-value]
