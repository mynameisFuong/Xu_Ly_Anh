"""Bounded, independent confirmation of people in a continuous camera stream."""

from collections import Counter, deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Lock
from time import monotonic
from uuid import uuid4

import numpy as np

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
    embedding: np.ndarray | None = None


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
    embedding: np.ndarray | None = None
    velocity: tuple = (0.0, 0.0)


class MultiFaceTracker:
    """Motion and appearance associate boxes; identity still requires fresh matching."""

    def __init__(self, min_hits=3, window_seconds=30, max_tracks=64, *,
                 min_interval_seconds=0.25, min_confirmation_seconds=0.5,
                 max_gap_seconds=10, appearance_threshold=0.6):
        if (min_hits < 1 or min_interval_seconds <= 0 or min_confirmation_seconds < 0
                or window_seconds < min_confirmation_seconds or max_gap_seconds <= 0):
            raise ValueError("Invalid temporal confirmation settings")
        self.min_hits = min_hits
        self.window_seconds = window_seconds
        self.max_tracks = max_tracks
        self.min_interval_seconds = min_interval_seconds
        self.min_confirmation_seconds = min_confirmation_seconds
        self.max_gap_seconds = max_gap_seconds
        self.appearance_threshold = appearance_threshold
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
            if track.seen < cutoff or now - track.seen > self.max_gap_seconds:
                del self._tracks[track_id]
            else:
                while track.hits and track.hits[0] < cutoff:
                    track.hits.popleft()
        edges = []
        for index, item in enumerate(observations):
            for track_id, track in self._tracks.items():
                dt = min(max(0, now - track.seen), 3)
                x, y, width, height = track.box
                predicted = (x + track.velocity[0] * dt, y + track.velocity[1] * dt, width, height)
                overlap = max(box_iou(item.box, predicted), box_iou(item.box, track.box))
                if overlap < 0.2:
                    continue
                appearance = 0.0
                if item.embedding is not None and track.embedding is not None:
                    distance = float(np.linalg.norm(item.embedding - track.embedding))
                    if not np.isfinite(distance) or distance > self.appearance_threshold:
                        continue
                    appearance = 0.3 * (1 - distance / self.appearance_threshold)
                edges.append((overlap + appearance, index, track_id))
        # Crossing/overlapping faces must rebuild evidence when association is ambiguous.
        for index in range(len(observations)):
            choices = sorted((edge for edge in edges if edge[1] == index), reverse=True)
            if len(choices) > 1 and choices[0][0] - choices[1][0] < 0.1:
                for _, _, track_id in choices:
                    self._tracks[track_id].hits.clear()
                    self._tracks[track_id].candidate = None
        edges.sort(reverse=True)
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
            dt = now - track.seen
            if dt > 0:
                track.velocity = ((item.box[0] - track.box[0]) / dt, (item.box[1] - track.box[1]) / dt)
            track.box, track.seen = item.box, now
            if not item.processed:
                confirmations.append(FaceConfirmation(track_id, min(len(track.hits), self.min_hits), False))
                continue
            candidate = item.student_id if duplicates[item.student_id] == 1 else None
            if candidate is None or candidate != track.candidate:
                track.candidate = candidate
                track.hits.clear()
            if candidate is not None:
                if not track.hits or now - track.hits[-1] >= self.min_interval_seconds:
                    track.hits.append(now)
                while len(track.hits) > max(self.min_hits, int(self.window_seconds / self.min_interval_seconds) + 1):
                    track.hits.popleft()
                if item.embedding is not None:
                    track.embedding = item.embedding.copy()
            confirmations.append(FaceConfirmation(track_id, min(len(track.hits), self.min_hits),
                                                  candidate is not None and len(track.hits) >= self.min_hits
                                                  and now - track.hits[0] >= self.min_confirmation_seconds))
        return confirmations


@dataclass
class StreamState:
    tracker: MultiFaceTracker
    last_seen: float
    last_frame_id: int = -1
    dimensions: tuple[int, int] | None = None
    busy: bool = False
    frame_digests: deque = field(default_factory=lambda: deque(maxlen=128))


class StreamStateStore:
    """One in-flight frame per stream; no image queues or unbounded tracking state."""

    def __init__(self, min_hits=3, window_seconds=30, max_streams=128, ttl_seconds=60, clock=monotonic,
                 **tracker_options):
        self.min_hits, self.window_seconds = min_hits, window_seconds
        self.max_streams, self.ttl_seconds = max_streams, ttl_seconds
        self.clock = clock
        self._streams = {}
        self._lock = Lock()
        self.tracker_options = tracker_options

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
                state = StreamState(MultiFaceTracker(self.min_hits, self.window_seconds, **self.tracker_options), now)
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
