"""Saat soyutlaması: üretimde sistem saati, testlerde sabit saat."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime:
        """Saat dilimli (UTC) geçerli zaman."""
        ...

    def timestamp(self) -> float:
        """Epoch saniye."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def timestamp(self) -> float:
        return self.now().timestamp()


class FixedClock:
    """Test için ayarlanabilir sabit saat."""

    def __init__(self, start: datetime | float | None = None) -> None:
        if start is None:
            start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        elif isinstance(start, (int, float)):
            start = datetime.fromtimestamp(start, tz=timezone.utc)
        elif start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        self._now: datetime = start.astimezone(timezone.utc)

    def now(self) -> datetime:
        return self._now

    def timestamp(self) -> float:
        return self._now.timestamp()

    def set(self, value: datetime | float) -> None:
        self._now = FixedClock(value).now()

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)
