"""Exercise source interruptions with three real decoders and the existing inference stack."""

import asyncio
from collections import Counter
from contextlib import aclosing, asynccontextmanager

from media_gateway.sampler import sample_camera
from tests.synthetic_stack_support import paced_video, wait_for


class InterruptibleReplay:
    def __init__(self, path, fps, clock):
        self.path, self.fps, self.clock = path, fps, clock
        self.fault = None
        self.retries = []
        self.stall_cancelled = False

    @asynccontextmanager
    async def open(self):
        if self.fault is not None:
            self.retries.append(self.clock())
            raise OSError('Synthetic source unavailable')
        async with paced_video(self.path, self.fps, lambda *_: None) as decoded:
            async with aclosing(self.frames(decoded)) as stream:
                yield stream

    async def frames(self, decoded):
        async for frame in decoded:
            if self.fault == 'eof':
                return
            if self.fault == 'stall':
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    self.stall_cancelled = True
                    raise
            yield frame


async def run_reconnect_soak(resolver, dispatcher, queue, paths):
    interval, frame_timeout, retry_initial, retry_max = 0.3, 2.0, 0.5, 1.0
    clock = asyncio.get_running_loop().time
    sources = {camera: InterruptibleReplay(path, fps, clock)
               for (camera, path), fps in zip(paths.items(), (10, 24, 30), strict=True)}
    assert all(await asyncio.gather(*(resolver.refresh(camera) for camera in sources)))
    offers_before = queue.offers.copy()
    taken_before = queue.taken.copy()
    losses_before = queue.losses.copy()
    last = {}
    emitted = Counter()
    unaffected_results = Counter()
    fault_window = None
    cycles = []

    async def consume():
        while True:
            queue.inference_busy = True
            try:
                row = await dispatcher.dispatch_one()
            finally:
                queue.inference_busy = False
            if row is not None:
                frame = row.frame
                camera = frame.camera_id
                active = resolver.current(camera, row.assignment_epoch)
                assert camera in sources and active and row.assignment == active.assignment
                assert frame.sample_interval == interval
                if camera in last:
                    previous, _ = last[camera]
                    assert frame.sampled_monotonic > previous.sampled_monotonic
                    assert (frame.source_epoch, frame.source_frame_index) > (
                        previous.source_epoch, previous.source_frame_index)
                if fault_window and frame.sampled_monotonic >= fault_window[1]:
                    assert camera != fault_window[0]
                    unaffected_results[camera] += 1
                last[camera] = (frame, clock())
                emitted[camera] += 1
            await asyncio.sleep(0.02)

    started = clock()
    async with asyncio.timeout(100), asyncio.TaskGroup() as group:
        tasks = [group.create_task(resolver.run()), group.create_task(consume())]
        for camera, source in sources.items():
            tasks.append(group.create_task(sample_camera(
                camera, source.open, queue, sample_interval=interval, frame_timeout=frame_timeout,
                retry_initial=retry_initial, retry_max=retry_max,
            )))
        try:
            await wait_for(lambda: len(last) == len(sources), 8)
            await asyncio.sleep(5)
            for mode in ('eof', 'stall'):
                for index, (camera, source) in enumerate(sources.items(), 1):
                    previous, _ = last[camera]
                    peer_epochs = {peer: last[peer][0].source_epoch
                                   for peer in sources if peer != camera}
                    unaffected_results.clear()
                    source.retries.clear()
                    source.stall_cancelled = False
                    faulted_at = clock()
                    fault_window = (camera, faulted_at)
                    source.fault = mode
                    await wait_for(lambda: len(source.retries) >= 2 and
                                   all(unaffected_results[peer] >= 2 for peer in peer_epochs), 8)
                    assert all(last[peer][0].source_epoch == epoch
                               for peer, epoch in peer_epochs.items())
                    assert all(b - a >= retry_initial - 0.01
                               for a, b in zip(source.retries, source.retries[1:]))
                    if mode == 'stall':
                        assert source.stall_cancelled

                    restored_at = clock()
                    fault_window = None
                    source.fault = None
                    await wait_for(lambda: last[camera][0].source_epoch > previous.source_epoch and
                                   last[camera][0].sampled_monotonic >= restored_at, 5)
                    _, received_at = last[camera]
                    cycles.append({
                        'camera': index, 'mode': mode, 'blocked_retries': len(source.retries),
                        'unaffected_results': sum(unaffected_results.values()),
                        'source_offline_s': round(restored_at - faulted_at, 3),
                        'restore_to_result_s': round(received_at - restored_at, 3),
                    })
                    await asyncio.sleep(5)
        finally:
            for task in tasks:
                task.cancel()

    taken = queue.taken - taken_before
    losses = queue.losses - losses_before
    pending = Counter()
    while (frame := queue.take()) is not None:
        pending[frame.camera_id] += 1
    assert 0 <= taken.total() - emitted.total() <= 1  # At most one request in flight at shutdown.
    cameras = []
    for index, camera in enumerate(sources, 1):
        offered = queue.offers[camera] - offers_before[camera]
        replaced = losses[camera, 'replacement_idle'] + losses[camera, 'replacement_dispatch_busy']
        rejected = losses[camera, 'policy_rejected']
        purged = losses[camera, 'purge_other']
        assert offered == taken[camera] + pending[camera] + replaced + rejected + purged
        assert emitted[camera] > 0 and pending[camera] <= 1
        cameras.append({'camera': index, 'offered': offered, 'emitted': emitted[camera],
                        'replaced': replaced, 'rejected': rejected, 'purged': purged,
                        'pending_at_shutdown': pending[camera],
                        'in_flight_at_shutdown': taken[camera] - emitted[camera]})
    return {'elapsed_s': round(clock() - started, 3), 'cycles': cycles, 'cameras': cameras}
