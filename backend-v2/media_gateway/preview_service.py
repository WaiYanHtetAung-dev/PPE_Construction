"""Private media read plane for bounded, short browser playback clips."""

import asyncio
import json
import os
from collections import deque
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass, field
from fractions import Fraction
from io import BytesIO
from pathlib import Path
from uuid import UUID

import av
import numpy as np
from anyio import to_thread
from fastapi import Depends, FastAPI, HTTPException, Response
from PIL import Image, ImageOps

from app.contracts.media_preview import MAX_PREVIEW_BYTES, CameraMediaStatus
from inference_worker.auth import read_token, require_token
from media_gateway.frame_queue import FrameQueue
from media_gateway.network_source import central_rtsp_source, stream_path
from media_gateway.sampler import sample_camera
from media_gateway.site_publisher import secret_file
from media_gateway.video_source import MAX_HEIGHT, MAX_WIDTH

FRAME_BYTES = MAX_WIDTH * MAX_HEIGHT * 3
PREVIEW_SIZE = (640, 360)
PREVIEW_FPS = 3
NO_STORE = {'Cache-Control': 'no-store'}


@dataclass
class StreamState:
    frames: deque[bytes] = field(default_factory=lambda: deque(maxlen=6))
    last_sample: float | None = None
    processing_latency_ms: float = 0
    opens: int = 0
    decoded_frames: int = 0
    decoded_bytes: int = 0
    dropped_frames: int = 0

    def status(self, now):
        online = self.last_sample is not None and now - self.last_sample < 5
        return CameraMediaStatus(state='online' if online else 'offline',
                                 preview_available=online and len(self.frames) >= 2)


class PreviewQueue(FrameQueue):
    def __init__(self, states):
        self.states = states
        super().__init__(max_cameras=len(states), max_bytes=len(states) * FRAME_BYTES,
                         max_frame_bytes=FRAME_BYTES)

    def offer(self, sample):
        replaced = sample.camera_id in self._pending
        admitted = super().offer(sample)
        if replaced or not admitted:
            self.states[sample.camera_id].dropped_frames += 1
        return admitted

    def depth(self, camera_id):
        return int(camera_id in self._pending)


def encode_clip(frames):
    with BytesIO() as output:
        with av.open(output, 'w', format='mp4') as video:
            stream = video.add_stream('libx264', rate=PREVIEW_FPS, options={'preset': 'ultrafast'})
            stream.width, stream.height = PREVIEW_SIZE
            stream.pix_fmt = 'yuv420p'
            stream.codec_context.thread_count = 1
            for index, data in enumerate(frames):
                pixels = np.frombuffer(data, dtype=np.uint8).reshape(PREVIEW_SIZE[1], PREVIEW_SIZE[0], 3)
                frame = av.VideoFrame.from_ndarray(pixels, format='rgb24')
                frame.pts = index
                frame.time_base = Fraction(1, PREVIEW_FPS)
                video.mux(stream.encode(frame))
            video.mux(stream.encode())
        return output.getvalue()


def create_preview_service(bindings, token):
    """Bindings map a camera UUID to its expected opaque alias and trusted source."""
    if not 1 <= len(bindings) <= 16:
        raise ValueError('Configure between one and sixteen pilot streams')
    states = {camera: StreamState() for camera in bindings}
    queue = PreviewQueue(states)
    encoder = asyncio.Lock()

    @asynccontextmanager
    async def watched(camera, source):
        state = states[camera]
        state.opens += 1

        async def observed(frames):
            async for frame in frames:
                state.decoded_frames += 1
                state.decoded_bytes += len(frame.data)
                yield frame

        try:
            async with source() as frames, aclosing(observed(frames)) as stream:
                yield stream
        finally:
            queue.discard(camera)
            state.frames.clear()
            state.last_sample = None

    async def consume():
        clock = asyncio.get_running_loop().time
        while True:
            if (sample := queue.take()) is None:
                await asyncio.sleep(0.02)
                continue
            state = states[sample.camera_id]
            with Image.frombytes('RGB', (sample.width, sample.height), sample.data) as image:
                state.frames.append(ImageOps.pad(image, PREVIEW_SIZE).tobytes())
            state.last_sample = sample.sampled_monotonic
            state.processing_latency_ms = (clock() - sample.sampled_monotonic) * 1000
            await asyncio.sleep(0)

    @asynccontextmanager
    async def lifespan(_app):
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(consume())]
            for camera, (_, source) in bindings.items():
                tasks.append(group.create_task(sample_camera(
                    camera, lambda camera=camera, source=source: watched(camera, source), queue,
                    sample_interval=1 / PREVIEW_FPS, frame_timeout=5, retry_initial=0.5, retry_max=5,
                )))
            try:
                yield
            finally:
                for task in tasks:
                    task.cancel()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None,
                  dependencies=[Depends(require_token(token))])

    def lookup(camera_id, stream_ref):
        camera = str(camera_id)
        binding = bindings.get(camera)
        if binding is None or binding[0] != stream_ref:
            raise HTTPException(404, 'Camera media unavailable')
        return states[camera]

    @app.get('/internal/v1/cameras/{camera_id}/status', response_model=CameraMediaStatus)
    async def status(camera_id: UUID, stream_ref: str, response: Response):
        response.headers.update(NO_STORE)
        return lookup(camera_id, stream_ref).status(asyncio.get_running_loop().time())

    @app.get('/internal/v1/cameras/{camera_id}/preview')
    async def preview(camera_id: UUID, stream_ref: str):
        state = lookup(camera_id, stream_ref)
        clock = asyncio.get_running_loop().time
        if not state.status(clock()).preview_available or encoder.locked():
            raise HTTPException(503, 'Camera preview unavailable')
        epoch = state.opens
        async with encoder:
            try:
                data = await to_thread.run_sync(encode_clip, tuple(state.frames))
            except (av.error.FFmpegError, ValueError):
                raise HTTPException(503, 'Camera preview unavailable') from None
        if (len(data) > MAX_PREVIEW_BYTES or state.opens != epoch
                or not state.status(clock()).preview_available):
            raise HTTPException(503, 'Camera preview unavailable')
        return Response(data, media_type='video/mp4', headers=NO_STORE)

    @app.get('/internal/v1/metrics')
    async def metrics():
        now = asyncio.get_running_loop().time()
        return {camera: {'online': state.status(now).state == 'online',
                         'reconnect_attempts': max(0, state.opens - 1),
                         'decoded_frames_total': state.decoded_frames,
                         'decoded_payload_bytes_total': state.decoded_bytes,
                         'queue_drops_total': state.dropped_frames, 'queue_depth': queue.depth(camera),
                         'processing_latency_ms': state.processing_latency_ms}
                for camera, state in states.items()}

    return app


def from_environment():
    with Path(os.environ['MEDIA_BINDINGS_FILE']).open(encoding='ascii') as source:
        raw = source.read(16385)
    if len(raw) > 16384:
        raise ValueError('Media bindings exceed the pilot limit')
    password = secret_file(os.environ['MEDIA_RTSP_PASSWORD_FILE'])
    host = os.environ['MEDIA_RTSP_HOST']
    port = int(os.environ['MEDIA_RTSP_PORT'])
    username = os.environ['MEDIA_RTSP_USER']
    bindings = {}
    paths = set()
    for key, entry in json.loads(raw).items():
        camera = str(UUID(key))
        alias = entry['stream_ref']
        path = stream_path(entry['path'])
        if camera in bindings or path in paths or not alias.startswith('stream:'):
            raise ValueError('Invalid media binding')
        stream_path(alias.removeprefix('stream:'))
        paths.add(path)
        bindings[camera] = (alias, central_rtsp_source(host, port, path, username, password))
    return create_preview_service(bindings, read_token(os.environ['MEDIA_GATEWAY_TOKEN_FILE']))
