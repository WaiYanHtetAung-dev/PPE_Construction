from typing import Literal

from pydantic import BaseModel

MAX_PREVIEW_BYTES = 2 * 1024 * 1024


class CameraMediaStatus(BaseModel):
    state: Literal['disabled', 'not_monitored', 'offline', 'online']
    preview_available: bool = False
