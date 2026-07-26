"""Draws detection boxes + person status labels onto a BGR frame using OpenCV."""

from __future__ import annotations

import cv2
import numpy as np

from detector import (
    Detection,
    PersonResult,
    HELMET_CLASS_IDS,
    VEST_CLASS_ID,
    HELMET_COLOR_HEX,
    VEST_COLOR_HEX,
    SECURE_COLOR_HEX,
    UNSECURE_COLOR_HEX,
)


def _hex_to_bgr(hex_color: str) -> tuple:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    return (b, g, r)


def _draw_box(frame, box, color_bgr, label: str, thickness: int = 2):
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    cv2.rectangle(frame, (x1, y1), (x2, y2), color_bgr, thickness)
    if label:
        (tw, th), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        ty1 = max(0, y1 - th - baseline - 4)
        cv2.rectangle(frame, (x1, ty1), (x1 + tw + 6, ty1 + th + baseline + 4), color_bgr, -1)
        text_color = (0, 0, 0) if sum(color_bgr) > 380 else (255, 255, 255)
        cv2.putText(
            frame,
            label,
            (x1 + 3, ty1 + th + 1),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            text_color,
            1,
            cv2.LINE_AA,
        )


def annotate_frame(
    frame: np.ndarray,
    persons: list[PersonResult],
    detections: list[Detection] | None = None,
    show_ppe_boxes: bool = True,
) -> np.ndarray:
    out = frame.copy()

    matched_ids = set()
    for p in persons:
        if p.helmet is not None:
            matched_ids.add(id(p.helmet))
        if p.vest is not None:
            matched_ids.add(id(p.vest))

    for p in persons:
        if show_ppe_boxes and p.helmet is not None:
            h_color = _hex_to_bgr(HELMET_COLOR_HEX.get(p.helmet.cls, "#F5C518"))
            _draw_box(out, p.helmet.box, h_color, f"{p.helmet.label} {p.helmet.conf:.2f}", 1)
        if show_ppe_boxes and p.vest is not None:
            v_color = _hex_to_bgr(VEST_COLOR_HEX)
            _draw_box(out, p.vest.box, v_color, f"vest {p.vest.conf:.2f}", 1)

        status_color = _hex_to_bgr(SECURE_COLOR_HEX if p.is_secure else UNSECURE_COLOR_HEX)
        label = "SECURE" if p.is_secure else f"UNSECURE (no {', '.join(p.missing)})"
        _draw_box(out, p.box, status_color, f"{label} {p.conf:.2f}", 2)

    # Any helmet/vest the model found that couldn't be tied to a person box
    # (e.g. a close-up shot with no full body visible) still gets drawn -
    # otherwise a real detection would silently disappear from the output.
    unmatched_count = 0
    if show_ppe_boxes and detections:
        for d in detections:
            if d.cls not in HELMET_CLASS_IDS and d.cls != VEST_CLASS_ID:
                continue
            if id(d) in matched_ids:
                continue
            unmatched_count += 1
            if d.cls == VEST_CLASS_ID:
                color = _hex_to_bgr(VEST_COLOR_HEX)
                label = f"vest (unassigned) {d.conf:.2f}"
            else:
                color = _hex_to_bgr(HELMET_COLOR_HEX.get(d.cls, "#F5C518"))
                label = f"{d.label} (unassigned) {d.conf:.2f}"
            _draw_box(out, d.box, color, label, 1)

    # Summary banner
    total = len(persons)
    secure = sum(1 for p in persons if p.is_secure)
    banner = f"Persons: {total}   Secure: {secure}   Unsecure: {total - secure}"
    if unmatched_count:
        banner += f"   |   {unmatched_count} PPE item(s) detected with no person box"
    cv2.rectangle(out, (0, 0), (out.shape[1], 28), (20, 20, 20), -1)
    cv2.putText(out, banner, (8, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

    return out
