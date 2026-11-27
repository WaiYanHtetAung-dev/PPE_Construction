"""Child process for decoding a configured source with FFmpeg via PyAV."""

import sys
from pathlib import Path

import av

from media_gateway.video_source import HEADER, MAX_HEIGHT, MAX_WIDTH


def decode(video, *, live=False) -> None:
    output = sys.stdout.buffer
    stream = video.streams.video[0]
    stream.codec_context.thread_count = 1
    if not 1 <= stream.width <= MAX_WIDTH or not 1 <= stream.height <= MAX_HEIGHT:
        raise ValueError('Video dimensions exceed decoder bounds')
    previous = None
    for frame in video.decode(stream):
        if not 1 <= frame.width <= MAX_WIDTH or not 1 <= frame.height <= MAX_HEIGHT:
            raise ValueError('Frame dimensions exceed decoder bounds')
        if frame.pts is None or not frame.time_base:
            if live:
                continue
            raise ValueError('Frame has no presentation timestamp')
        timestamp = float(frame.pts * frame.time_base)
        if live and previous is not None and timestamp <= previous:
            continue
        previous = timestamp
        output.write(HEADER.pack(timestamp, frame.width, frame.height))
        output.write(frame.to_ndarray(format='rgb24').tobytes())
        output.flush()


if __name__ == '__main__':
    if sys.argv[1] == '--central-rtsp':
        endpoint = sys.stdin.buffer.read(513)
        if not 1 <= len(endpoint) <= 512:
            raise ValueError('Invalid central decoder configuration')
        with av.open(endpoint.decode('ascii'), format='rtsp', timeout=(3, 3),
                     options={'rtsp_transport': 'tcp', 'allowed_media_types': 'video',
                              'protocol_whitelist': 'tcp,rtp'}) as video:
            decode(video, live=True)
    else:
        with Path(sys.argv[1]).open('rb') as source, av.open(
            source, format='mov', options={'enable_drefs': '0'},
        ) as video:
            decode(video)
