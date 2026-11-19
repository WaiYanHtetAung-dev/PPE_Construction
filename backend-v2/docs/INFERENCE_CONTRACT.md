# Independent AI Model Inference Contract v1

The Backend **never imports** `ultralytics`, `torch` or any `.pt` checkpoint. Future inference service implements this JSON contract independently over authenticated HTTP/gRPC or an equivalent message queue.

## Request example (planned service boundary)

```json
{
  "schema_version": "1.0",
  "request_id": "8e38f4fb-57e1-4ae8-a56e-fc1e80c184cf",
  "frame_id": "camera-01:2026-11-18T04:00:00.000Z",
  "model_key": "ppe-yolo",
  "model_version": "1.0.0",
  "frame": {
    "object_key": "frames/camera-01/frame-1234.jpg",
    "width": 1280,
    "height": 720,
    "content_type": "image/jpeg"
  },
  "options": { "confidence_threshold": 0.35 }
}
```

## Response example

```json
{
  "schema_version": "1.0",
  "request_id": "8e38f4fb-57e1-4ae8-a56e-fc1e80c184cf",
  "frame_id": "camera-01:2026-11-18T04:00:00.000Z",
  "model_key": "ppe-yolo",
  "model_version": "1.0.0",
  "inference_ms": 25.4,
  "detections": [
    {"class_key": "person", "original_class": "person", "score": 0.97,
     "bbox_xyxy": [105, 50, 420, 700], "attributes": {}},
    {"class_key": "helmet", "original_class": "yellow helmet", "score": 0.93,
     "bbox_xyxy": [188, 47, 246, 126], "attributes": {"color": "yellow"}},
    {"class_key": "vest", "original_class": "vest", "score": 0.90,
     "bbox_xyxy": [156, 220, 365, 440], "attributes": {}}
  ]
}
```

## V1 `finalboss.pt` canonical class mapping

| Original YOLO class ID | Label | Canonical class |
|---|---|---|
| 0 | black helmet | helmet(color=black) |
| 1 | blue helmet | helmet(color=blue) |
| 2 | green helmet | helmet(color=green) |
| 3 | person | person |
| 4 | red helmet | helmet(color=red) |
| 5 | vest | vest |
| 6 | white helmet | helmet(color=white) |
| 7 | yellow helmet | helmet(color=yellow) |

Inference service outputs **detections only**; person↔PPE association and temporal violation confirmation belong in a downstream rules/incident service.

Rules: coordinates are image-space pixels `[x1,y1,x2,y2]` within the frame dimensions; score in [0,1]; unknown classes are not silently mapped; missing supported classes may mean 'unknown', not automatically noncompliance. Add API contract version for breaking changes. A frame object key must be resolved with service credentials, never via arbitrary client URLs. Validate width/height and box bounds at the serving boundary; schema currently validates bbox order and non-negative values only.

The package contains **Pydantic contract models**, not an actual AI inference server or GPU implementation. See `app/contracts/inference.py`.
