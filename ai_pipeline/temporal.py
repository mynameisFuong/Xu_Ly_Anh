from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


@dataclass
class TemporalConfirmer:
    min_hits: int = 3
    window_seconds: int = 4
    _hits: dict[int, deque[datetime]] = field(default_factory=dict)

    def observe(self, student_id: int, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        window_start = current - timedelta(seconds=self.window_seconds)
        hits = self._hits.setdefault(student_id, deque())
        hits.append(current)
        while hits and hits[0] < window_start:
            hits.popleft()
        return len(hits) >= self.min_hits
