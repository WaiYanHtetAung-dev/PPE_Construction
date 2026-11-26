"""Bounded handoff from trusted frame samplers to inference dispatchers."""

from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime
from threading import RLock


@dataclass(frozen=True, slots=True)
class SampledFrame:
    camera_id: str
    data: bytes
    received_at: datetime | None = None
    source_timestamp: float | None = None
    source_frame_index: int | None = None
    source_epoch: int | None = None
    sampled_monotonic: float | None = None
    sample_interval: float | None = None
    width: int | None = None
    height: int | None = None
    assignment_epoch: int | None = None


class FrameQueue:
    """Keep one pending frame per camera and serve cameras in arrival order."""

    def __init__(self, *, max_cameras: int, max_bytes: int, max_frame_bytes: int):
        if max_cameras < 1 or not 1 <= max_frame_bytes <= max_bytes:
            raise ValueError('Invalid frame queue limits')
        self._max_cameras = max_cameras
        self._max_bytes = max_bytes
        self._max_frame_bytes = max_frame_bytes
        self._pending: OrderedDict[str, SampledFrame] = OrderedDict()
        self._pending_bytes = 0
        self._lock = RLock()
        self._assignment_guard = None

    def bind_assignments(self, guard):
        with self._lock:
            if self._assignment_guard is not None:
                raise ValueError('Frame queue already has an assignment guard')
            self._assignment_guard = guard
            self._pending.clear()
            self._pending_bytes = 0

    def discard(self, camera_id: str) -> None:
        with self._lock:
            frame = self._pending.pop(camera_id, None)
            if frame is not None:
                self._pending_bytes -= len(frame.data)

    def offer(self, frame: SampledFrame) -> bool:
        """Return false when the incoming frame cannot fit without evicting another camera."""
        if not frame.camera_id or type(frame.data) is not bytes:
            raise ValueError('Expected a camera identifier and immutable frame bytes')
        size = len(frame.data)
        if not 1 <= size <= self._max_frame_bytes:
            return False

        with self._lock:
            if self._assignment_guard is not None:
                epoch = self._assignment_guard(frame.camera_id)
                if epoch is None or (frame.assignment_epoch is not None and frame.assignment_epoch != epoch):
                    return False
                frame = replace(frame, assignment_epoch=epoch)
            previous = self._pending.get(frame.camera_id)
            if previous is None and len(self._pending) >= self._max_cameras:
                return False
            replaced_bytes = len(previous.data) if previous is not None else 0
            total = self._pending_bytes - replaced_bytes + size
            if total > self._max_bytes:
                return False

            # Assigning an existing key preserves its turn in the ordered dictionary.
            self._pending[frame.camera_id] = frame
            self._pending_bytes = total
            return True

    def take(self) -> SampledFrame | None:
        with self._lock:
            if not self._pending:
                return None
            _, frame = self._pending.popitem(last=False)
            self._pending_bytes -= len(frame.data)
            return frame
