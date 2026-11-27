from io import BytesIO

import av
import pytest

from media_gateway.network_source import central_rtsp_source
from media_gateway.preview_service import PREVIEW_SIZE, encode_clip
from media_gateway.site_publisher import publish_command


def test_network_source_rejects_non_ingress_and_unsafe_paths():
    for host, path in (('example.invalid', 'fixture'), ('8.8.8.8', 'fixture'),
                       ('127.0.0.1', '../fixture'), ('127.0.0.1', 'fixture?pass=oops')):
        with pytest.raises(ValueError):
            central_rtsp_source(host, 8554, path, 'reader', 's' * 24)
    with pytest.raises(ValueError):
        publish_command('rtsp://8.8.8.8/test', 'ingress.invalid', 8890, 'fixture', 'site', 'p' * 24, 's' * 24)


def test_preview_encoder_produces_decodable_bounded_h264():
    clip = encode_clip([bytes(PREVIEW_SIZE[0] * PREVIEW_SIZE[1] * 3)] * 3)
    assert clip[4:8] == b'ftyp'
    with av.open(BytesIO(clip)) as video:
        assert video.streams.video[0].codec_context.name == 'h264'
        assert len(list(video.decode(video=0))) == 3
