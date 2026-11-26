"""Bounded handoff from trusted frame samplers to inference dispatchers."""

from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True, slots=True)
class SampledFrame:
    camera_id: str
    data: bytes


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
        self._lock = Lock()

    def offer(self, frame: SampledFrame) -> bool:
        """Return false when the incoming frame cannot fit without evicting another camera."""
        if not frame.camera_id or type(frame.data) is not bytes:
            raise ValueError('Expected a camera identifier and immutable frame bytes')
        size = len(frame.data)
        if not 1 <= size <= self._max_frame_bytes:
            return False

        with self._lock:
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
