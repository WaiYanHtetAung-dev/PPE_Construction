"""Read RGB frames and source PTS from a cancellable local MP4 decoder."""

import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from struct import Struct

HEADER = Struct('!dHH')
MAX_WIDTH, MAX_HEIGHT = 1920, 1080


@dataclass(frozen=True, slots=True)
class DecodedFrame:
    data: bytes
    received_at: datetime
    source_timestamp: float
    index: int
    width: int
    height: int


async def _frames(process: asyncio.subprocess.Process) -> AsyncIterator[DecodedFrame]:
    assert process.stdout is not None
    index = 0
    previous = None
    while True:
        try:
            header = await process.stdout.readexactly(HEADER.size)
            pts, width, height = HEADER.unpack(header)
            if (not isfinite(pts) or (previous is not None and pts <= previous)
                    or not 1 <= width <= MAX_WIDTH or not 1 <= height <= MAX_HEIGHT):
                raise OSError('Invalid decoder frame metadata')
            payload = await process.stdout.readexactly(width * height * 3)
        except asyncio.IncompleteReadError as error:
            if not error.partial and error.expected == HEADER.size and await process.wait() == 0:
                return
            raise OSError('Local video decoder failed or returned a truncated frame') from None
        previous = pts
        yield DecodedFrame(payload, datetime.now(UTC), pts, index, width, height)
        index += 1


@asynccontextmanager
async def local_video_source(path: Path) -> AsyncIterator[AsyncIterator[DecodedFrame]]:
    """Open a trusted local MP4 fixture. Never accept a network source."""
    if path.as_posix().startswith('//') or path.suffix.lower() != '.mp4':
        raise OSError('Expected a local MP4 file')
    path = path.resolve()
    if path.as_posix().startswith('//') or path.suffix.lower() != '.mp4' or not path.is_file():
        raise OSError('Expected a local MP4 file')
    process = await asyncio.create_subprocess_exec(
        sys.executable, '-B', '-m', 'media_gateway._decode_video', str(path),
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    frames = _frames(process)
    try:
        yield frames
    finally:
        await frames.aclose()
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.communicate()
