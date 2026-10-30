"""Bounded, independent confirmation of people in a continuous camera stream."""

from collections import Counter, deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Lock
from time import monotonic
from uuid import uuid4

from ai_pipeline.detection import box_iou


class StaleFrameError(ValueError):
    pass


class StreamBusyError(RuntimeError):
    pass


@dataclass(frozen=True)
class FaceObservation:
    box: tuple[int, int, int, int]
    student_id: int | None
    processed: bool = True


@dataclass(frozen=True)
class FaceConfirmation:
    track_id: str
    hits: int
    confirmed: bool


@dataclass
class _Track:
    box: tuple[int, int, int, int]
    seen: float
    candidate: int | None = None
    hits: deque = field(default_factory=deque)


class MultiFaceTracker:
    """Geometry associates boxes; every identity decision requires fresh matching."""

    def __init__(self, min_hits=3, window_seconds=30, max_tracks=64):
        self.min_hits = min_hits
        self.window_seconds = window_seconds
        self.max_tracks = max_tracks
        self._tracks = {}
        self._last_frame_id = -1

    def clear(self):
        self._tracks.clear()

    def update(self, observations, *, frame_id, now):
        if frame_id <= self._last_frame_id:
            raise StaleFrameError("Frame sequence has already been processed")
        self._last_frame_id = frame_id
        cutoff = now - self.window_seconds
        for track_id, track in list(self._tracks.items()):
            if track.seen < cutoff:
                del self._tracks[track_id]
            else:
                while track.hits and track.hits[0] < cutoff:
                    track.hits.popleft()
        edges = sorted(((box_iou(item.box, track.box), index, track_id)
                        for index, item in enumerate(observations)
                        for track_id, track in self._tracks.items()
                        if box_iou(item.box, track.box) >= 0.2), reverse=True)
        assignments, used = {}, set()
        for _overlap, index, track_id in edges:
            if index not in assignments and track_id not in used:
                assignments[index] = track_id
                used.add(track_id)
        # An absent face loses its votes, independently of the other faces.
        for track_id, track in self._tracks.items():
            if track_id not in used:
                track.candidate = None
                track.hits.clear()
        duplicates = Counter(item.student_id for item in observations if item.processed and item.student_id is not None)
        confirmations = []
        for index, item in enumerate(observations):
            track_id = assignments.get(index)
            if track_id is None:
                if len(self._tracks) >= self.max_tracks:
                    idle = [key for key in self._tracks if key not in used]
                    if not idle:
                        confirmations.append(FaceConfirmation(f"overflow-{frame_id}-{index}", 0, False))
                        continue
                    del self._tracks[min(idle, key=lambda key: self._tracks[key].seen)]
                track_id = uuid4().hex[:12]
                self._tracks[track_id] = _Track(item.box, now)
            used.add(track_id)
            track = self._tracks[track_id]
            track.box, track.seen = item.box, now
            if not item.processed:
                confirmations.append(FaceConfirmation(track_id, len(track.hits), False))
                continue
            candidate = item.student_id if duplicates[item.student_id] == 1 else None
            if candidate is None or candidate != track.candidate:
                track.candidate = candidate
                track.hits.clear()
            if candidate is not None:
                track.hits.append(now)
                while len(track.hits) > self.min_hits:
                    track.hits.popleft()
            confirmations.append(FaceConfirmation(track_id, len(track.hits),
                                                  candidate is not None and len(track.hits) >= self.min_hits))
        return confirmations


@dataclass
class StreamState:
    tracker: MultiFaceTracker
    last_seen: float
    last_frame_id: int = -1
    dimensions: tuple[int, int] | None = None
    busy: bool = False


class StreamStateStore:
    """One in-flight frame per stream; no image queues or unbounded tracking state."""

    def __init__(self, min_hits=3, window_seconds=30, max_streams=128, ttl_seconds=60, clock=monotonic):
        self.min_hits, self.window_seconds = min_hits, window_seconds
        self.max_streams, self.ttl_seconds = max_streams, ttl_seconds
        self.clock = clock
        self._streams = {}
        self._lock = Lock()

    @contextmanager
    def checkout(self, key, frame_id):
        with self._lock:
            now = self.clock()
            for old_key, old_state in list(self._streams.items()):
                if not old_state.busy and old_state.last_seen < now - self.ttl_seconds:
                    del self._streams[old_key]
            state = self._streams.get(key)
            if state is None:
                if len(self._streams) >= self.max_streams:
                    idle = [key for key, item in self._streams.items() if not item.busy]
                    if not idle:
                        raise StreamBusyError("All stream processing slots are busy")
                    del self._streams[min(idle, key=lambda key: self._streams[key].last_seen)]
                state = StreamState(MultiFaceTracker(self.min_hits, self.window_seconds), now)
                self._streams[key] = state
            if state.busy:
                raise StreamBusyError("This stream is already processing a frame")
            if frame_id <= state.last_frame_id:
                raise StaleFrameError("Frame sequence has already been processed")
            state.busy, state.last_frame_id = True, frame_id
        try:
            yield state
        finally:
            with self._lock:
                state.busy, state.last_seen = False, self.clock()
