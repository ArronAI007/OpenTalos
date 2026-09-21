import time


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, recovery_seconds: float = 300) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self._failure_counts: dict[str, int] = {}
        self._opened_at: dict[str, float] = {}

    def allow(self, name: str) -> bool:
        opened_at = self._opened_at.get(name)
        if opened_at is None:
            return True
        if time.monotonic() - opened_at >= self.recovery_seconds:
            del self._opened_at[name]
            self._failure_counts[name] = 0
            return True
        return False

    def record(self, name: str, *, success: bool) -> None:
        if success:
            self._failure_counts[name] = 0
            self._opened_at.pop(name, None)
            return
        count = self._failure_counts.get(name, 0) + 1
        self._failure_counts[name] = count
        if count >= self.failure_threshold:
            self._opened_at[name] = time.monotonic()
