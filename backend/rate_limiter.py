import time
from collections import defaultdict
from threading import Lock
from typing import Dict, List
from fastapi import HTTPException, Request, status


class InMemoryRateLimiter:
    """
    Sliding window in-memory rate limiter for authentication and expensive endpoints.
    Tracks timestamps per key (e.g., client IP or username).
    """

    def __init__(self):
        self._history: Dict[str, List[float]] = defaultdict(list)
        self._lock = Lock()

    def check(self, key: str, max_requests: int, window_seconds: int = 60) -> None:
        """
        Records an access attempt and raises HTTP 429 if the rate limit is exceeded.
        """
        now = time.time()
        with self._lock:
            # Prune timestamps older than window
            window_start = now - window_seconds
            valid_timestamps = [t for t in self._history[key] if t > window_start]

            if len(valid_timestamps) >= max_requests:
                earliest = valid_timestamps[0]
                retry_after = max(1, int(earliest + window_seconds - now))
                self._history[key] = valid_timestamps
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded: maximum {max_requests} requests per {window_seconds}s. Try again in {retry_after}s.",
                    headers={"Retry-After": str(retry_after)},
                )

            valid_timestamps.append(now)
            self._history[key] = valid_timestamps

    def clear(self):
        """Clears all recorded rate limit history (useful for test isolation)."""
        with self._lock:
            self._history.clear()


# Global rate limiter instance
rate_limiter = InMemoryRateLimiter()


def get_client_ip(request: Request) -> str:
    """Extracts client IP address safely from request headers or client socket."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


def rate_limit_auth(request: Request) -> None:
    """Enforces 10 requests per minute for authentication endpoints."""
    ip = get_client_ip(request)
    rate_limiter.check(f"auth:{ip}", max_requests=10, window_seconds=60)


def rate_limit_chat(request: Request) -> None:
    """Enforces 30 requests per minute for expensive AI chat inference endpoints."""
    ip = get_client_ip(request)
    rate_limiter.check(f"chat:{ip}", max_requests=30, window_seconds=60)
