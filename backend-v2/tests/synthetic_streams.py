"""MediaMTX configuration and H.264 generation shared by synthetic tests."""

import json

HOST = '127.0.0.1'


def media_config(path, rtsp, users, paths, srt=None, metrics=None, *, rtsp_host=HOST, srt_host=HOST):
    settings = dict(logLevel='error', rtspAddress=f'{rtsp_host}:{rtsp}', rtspTransports=['tcp'],
                    authInternalUsers=users, paths=paths, rtmp=False, hls=False, webrtc=False,
                    moq=False, srt=srt is not None, metrics=metrics is not None, readTimeout='4s',
                    pathDefaults={'overridePublisher': False})
    if srt is not None:
        settings['srtAddress'] = f'{srt_host}:{srt}'
    if metrics is not None:
        settings['metricsAddress'] = f'{HOST}:{metrics}'
    path.touch(mode=0o600, exist_ok=False)
    path.write_text(json.dumps(settings), encoding='ascii')  # JSON is valid YAML.
    return path


def permission(user, password, action, path=''):
    return {'user': user, 'pass': password, 'permissions': [{'action': action, 'path': path}]}


def camera_command(url, width, height):
    return ('ffmpeg', '-nostdin', '-loglevel', 'quiet', '-re', '-f', 'lavfi', '-i',
            f'testsrc2=size={width}x{height}:rate=10', '-c:v', 'libx264', '-threads', '1',
            '-preset', 'ultrafast', '-tune', 'zerolatency', '-g', '10', '-f', 'rtsp',
            '-rtsp_transport', 'tcp', url)
