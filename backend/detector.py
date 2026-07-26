"""
PPE Detection engine.

Wraps the Ultralytics YOLO model (trained classes: black helmet, blue helmet,
green helmet, person, red helmet, vest, white helmet, yellow helmet) and adds
a person <-> PPE matching step so each detected person is classified as
SECURE (helmet + vest) or UNSECURE (missing one or both).

Matching strategy
------------------
A raw IoU match between a "person" box and a "helmet"/"vest" box fails a lot
in practice because the helmet/vest boxes are small and sit only on part of
the person's box (helmet near the top, vest around the torso), so overlap
with the full person box can be tiny or the boxes can be side by side for
people standing close together.

Instead, for every person box we build two sub-regions:
  - head_zone  -> upper ~45% of the box, expanded slightly sideways
  - torso_zone -> middle band (15%-95% of height), expanded slightly sideways

A helmet is assigned to a person if the helmet's center point lands inside
that person's head_zone (falling back to best horizontal overlap if a
helmet's center misses every zone, e.g. a tilted head at the frame edge).
A vest is matched the same way against torso_zone. Each person keeps only
its best (highest confidence) helmet and vest match.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from ultralytics import YOLO

# ---------------------------------------------------------------------------
# Class map exactly as embedded in the provided model checkpoint.
# ---------------------------------------------------------------------------
CLASS_NAMES = {
    0: "black helmet",
    1: "blue helmet",
    2: "green helmet",
    3: "person",
    4: "red helmet",
    5: "vest",
    6: "white helmet",
    7: "yellow helmet",
}

PERSON_CLASS_ID = 3
VEST_CLASS_ID = 5
HELMET_CLASS_IDS = {0, 1, 2, 4, 6, 7}

HELMET_COLOR_HEX = {
    0: "#111111",   # black helmet
    1: "#2563EB",   # blue helmet
    2: "#16A34A",   # green helmet
    4: "#DC2626",   # red helmet
    6: "#F5F5F5",   # white helmet
    7: "#F5C518",   # yellow helmet
}
VEST_COLOR_HEX = "#F97316"
SECURE_COLOR_HEX = "#22C55E"
UNSECURE_COLOR_HEX = "#EF4444"


@dataclass
class Detection:
    box: tuple  # x1, y1, x2, y2 (pixel coords)
    cls: int
    conf: float

    @property
    def label(self) -> str:
        return CLASS_NAMES.get(self.cls, str(self.cls))

    @property
    def center(self) -> tuple:
        x1, y1, x2, y2 = self.box
        return (x1 + x2) / 2.0, (y1 + y2) / 2.0


@dataclass
class PersonResult:
    box: tuple
    conf: float
    helmet: Optional[Detection] = None
    vest: Optional[Detection] = None

    @property
    def has_helmet(self) -> bool:
        return self.helmet is not None

    @property
    def has_vest(self) -> bool:
        return self.vest is not None

    @property
    def is_secure(self) -> bool:
        return self.has_helmet and self.has_vest

    @property
    def status(self) -> str:
        return "secure" if self.is_secure else "unsecure"

    @property
    def missing(self) -> list:
        m = []
        if not self.has_helmet:
            m.append("helmet")
        if not self.has_vest:
            m.append("vest")
        return m

    def to_dict(self) -> dict:
        return {
            "box": [round(v, 1) for v in self.box],
            "confidence": round(self.conf, 3),
            "status": self.status,
            "has_helmet": self.has_helmet,
            "has_vest": self.has_vest,
            "helmet_color": self.helmet.label.replace(" helmet", "") if self.helmet else None,
            "helmet_confidence": round(self.helmet.conf, 3) if self.helmet else None,
            "vest_confidence": round(self.vest.conf, 3) if self.vest else None,
            "missing": self.missing,
        }


def _head_zone(box: tuple) -> tuple:
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    return (x1 - 0.15 * w, y1 - 0.25 * h, x2 + 0.15 * w, y1 + 0.45 * h)


def _torso_zone(box: tuple) -> tuple:
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    return (x1 - 0.10 * w, y1 + 0.15 * h, x2 + 0.10 * w, y1 + 0.95 * h)


def _point_in_box(px: float, py: float, box: tuple) -> bool:
    x1, y1, x2, y2 = box
    return x1 <= px <= x2 and y1 <= py <= y2


def _horizontal_overlap_ratio(item_box: tuple, person_box: tuple) -> float:
    """Fallback score: how much of the item's width overlaps the person's width."""
    ix1, _, ix2, _ = item_box
    px1, _, px2, _ = person_box
    inter = max(0.0, min(ix2, px2) - max(ix1, px1))
    item_w = max(1e-6, ix2 - ix1)
    return inter / item_w


def match_ppe_to_persons(detections: list[Detection]) -> list[PersonResult]:
    """Associate helmet/vest detections with the nearest matching person."""
    persons = [
        PersonResult(box=d.box, conf=d.conf)
        for d in detections
        if d.cls == PERSON_CLASS_ID
    ]
    if not persons:
        return []

    head_zones = [_head_zone(p.box) for p in persons]
    torso_zones = [_torso_zone(p.box) for p in persons]

    helmets = sorted(
        (d for d in detections if d.cls in HELMET_CLASS_IDS),
        key=lambda d: d.conf,
        reverse=True,
    )
    vests = sorted(
        (d for d in detections if d.cls == VEST_CLASS_ID),
        key=lambda d: d.conf,
        reverse=True,
    )

    def assign(items: list[Detection], zones: list[tuple], attr: str) -> None:
        for item in items:
            cx, cy = item.center
            candidates = [i for i, z in enumerate(zones) if _point_in_box(cx, cy, z)]
            if not candidates:
                # Fallback: best horizontal-overlap person within a loose distance.
                scored = [
                    (i, _horizontal_overlap_ratio(item.box, persons[i].box))
                    for i in range(len(persons))
                ]
                scored = [s for s in scored if s[1] > 0.15]
                if not scored:
                    continue
                candidates = [max(scored, key=lambda s: s[1])[0]]

            # Prefer the candidate person without this item yet; among ties
            # prefer the smallest person box (closest / most specific match).
            def sort_key(i):
                already = getattr(persons[i], attr) is not None
                area = (persons[i].box[2] - persons[i].box[0]) * (
                    persons[i].box[3] - persons[i].box[1]
                )
                return (already, area)

            best_idx = min(candidates, key=sort_key)
            current = getattr(persons[best_idx], attr)
            if current is None or item.conf > current.conf:
                setattr(persons[best_idx], attr, item)

    assign(helmets, head_zones, "helmet")
    assign(vests, torso_zones, "vest")
    return persons


class PPEDetector:
    def __init__(self, weights_path: str, device: str | None = None, conf: float = 0.35, imgsz: int = 640):
        self.model = YOLO(weights_path)
        self.device = device  # None -> ultralytics auto-picks (GPU if available, else CPU)
        self.conf = conf
        self.imgsz = imgsz
        # Ultralytics' predictor isn't guaranteed safe for concurrent calls
        # from multiple threads. The app now calls infer() from the async
        # event loop (image/video/webcam requests) AND from background RTSP
        # camera-worker threads at the same time, so every call is
        # serialized through this lock rather than risking a race inside
        # the model's internal state.
        self._lock = threading.Lock()

    def infer(self, image: np.ndarray) -> tuple[list[Detection], list[PersonResult], float]:
        """Run detection on a BGR numpy image. Returns (raw detections, matched persons, inference_ms)."""
        t0 = time.time()
        with self._lock:
            results = self.model.predict(
                source=image,
                conf=self.conf,
                imgsz=self.imgsz,
                device=self.device,
                verbose=False,
            )
        elapsed_ms = (time.time() - t0) * 1000

        detections: list[Detection] = []
        r = results[0]
        if r.boxes is not None:
            for box in r.boxes:
                xyxy = box.xyxy[0].tolist()
                cls = int(box.cls[0].item())
                conf = float(box.conf[0].item())
                detections.append(Detection(box=tuple(xyxy), cls=cls, conf=conf))

        persons = match_ppe_to_persons(detections)
        return detections, persons, elapsed_ms

    @staticmethod
    def summarize(persons: list[PersonResult]) -> dict:
        total = len(persons)
        secure = sum(1 for p in persons if p.is_secure)
        return {
            "total_persons": total,
            "secure": secure,
            "unsecure": total - secure,
        }
