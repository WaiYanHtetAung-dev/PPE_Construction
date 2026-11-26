"""Child process for decoding trusted local fixture files with FFmpeg via PyAV."""

import sys
from pathlib import Path

import av

from media_gateway.video_source import HEADER, MAX_HEIGHT, MAX_WIDTH


def decode(path: Path) -> None:
    output = sys.stdout.buffer
    with path.open('rb') as source, av.open(source, format='mov', options={'enable_drefs': '0'}) as video:
        stream = video.streams.video[0]
        stream.codec_context.thread_count = 1
        if not 1 <= stream.width <= MAX_WIDTH or not 1 <= stream.height <= MAX_HEIGHT:
            raise ValueError('Video dimensions exceed decoder bounds')
        for frame in video.decode(stream):
            if not 1 <= frame.width <= MAX_WIDTH or not 1 <= frame.height <= MAX_HEIGHT:
                raise ValueError('Frame dimensions exceed decoder bounds')
            if frame.pts is None or not frame.time_base:
                raise ValueError('Frame has no presentation timestamp')
            output.write(HEADER.pack(float(frame.pts * frame.time_base), frame.width, frame.height))
            output.write(frame.to_ndarray(format='rgb24').tobytes())
            output.flush()


if __name__ == '__main__':
    decode(Path(sys.argv[1]))
