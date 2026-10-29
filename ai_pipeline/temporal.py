from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import Lock
from time import monotonic


@dataclass
class TemporalConfirmer:
    min_hits: int = 3
    window_seconds: int = 4
    _hits: dict[int, deque[datetime]] = field(default_factory=dict)

    def reset(self) -> None:
        self._hits.clear()

    def observe(self, student_id: int, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        window_start = current - timedelta(seconds=self.window_seconds)
        # A different candidate must start a new continuous observation sequence.
        for previous_id in list(self._hits):
            if previous_id != student_id:
                del self._hits[previous_id]
        hits = self._hits.setdefault(student_id, deque())
        hits.append(current)
        while hits and hits[0] < window_start:
            hits.popleft()
        return len(hits) >= self.min_hits


class CameraConfirmationStore:
    """Bounded per-process confirmation for upgraded camera clients, not PAD proof."""

    def __init__(self, min_hits=3, window_seconds=4, max_streams=128, clock=monotonic):
        self.min_hits = min_hits
        self.window_seconds = window_seconds
        self.max_streams = max_streams
        self.clock = clock
        self._streams = {}
        self._lock = Lock()

    def reset(self, key):
        with self._lock:
            self._streams.pop(key, None)

    def observe(self, key, student_id):
        now = self.clock()
        with self._lock:
            for old_key, (_candidate, hits) in list(self._streams.items()):
                if not hits or hits[-1] < now - self.window_seconds:
                    del self._streams[old_key]
            previous_id, hits = self._streams.get(key, (student_id, deque()))
            if previous_id != student_id:
                hits = deque()
            while hits and hits[0] < now - self.window_seconds:
                hits.popleft()
            hits.append(now)
            while len(hits) > self.min_hits:
                hits.popleft()
            if key not in self._streams and len(self._streams) >= self.max_streams:
                oldest = min(self._streams, key=lambda item: self._streams[item][1][-1])
                del self._streams[oldest]
            self._streams[key] = (student_id, hits)
            return len(hits) >= self.min_hits
