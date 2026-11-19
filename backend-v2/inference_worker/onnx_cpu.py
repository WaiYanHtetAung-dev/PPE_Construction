"""CPU-only, path-free adapter for the approved Finalboss raw ONNX profile."""

import json
from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
from math import isfinite

import numpy as np
import onnx
import onnxruntime as ort
from PIL import Image

from app.contracts.inference import Detection, FrameRef, InferenceRequest

LABELS = ('black helmet', 'blue helmet', 'green helmet', 'person',
          'red helmet', 'vest', 'white helmet', 'yellow helmet')
PROFILE = 'finalboss-yolo11-raw-v1'
SIZE = 640
OUTPUT = (1, 12, 8400)
OPSET = 17
NMS_IOU = 0.7
MAX_DETECTIONS = 300
MAX_MODEL_BYTES = 256 * 1024**2
MAX_FRAME_PIXELS = 16 * 1024**2


def validate_graph(artifact: bytes):
    if type(artifact) is not bytes or not 0 < len(artifact) <= MAX_MODEL_BYTES:
        raise ValueError('Expected bounded immutable ONNX bytes')
    model = onnx.load_model_from_string(artifact)
    metadata = {entry.key: entry.value for entry in model.metadata_props}
    if (len(metadata) != len(model.metadata_props) or metadata.get('ppe.profile') != PROFILE
            or json.loads(metadata.get('ppe.labels', 'null')) != list(LABELS)):
        raise ValueError('Unexpected ONNX profile or class map')
    if (model.functions or model.training_info
            or [(item.domain, item.version) for item in model.opset_import] != [('', OPSET)]):
        raise ValueError('Unsupported ONNX operator profile')
    # Traverse tensors in initializers and attributes, including nested subgraphs.
    pending = [model.graph]
    while pending:
        message = pending.pop()
        if isinstance(message, onnx.TensorProto) and (message.external_data or message.data_location):
            raise ValueError('External ONNX tensor data is unsupported')
        if isinstance(message, onnx.NodeProto) and (
            message.domain not in ('', 'ai.onnx') or message.op_type == 'NonMaxSuppression'
        ):
            raise ValueError('Unsupported ONNX operator')
        for field, value in message.ListFields():
            if field.message_type is not None:
                pending.extend(value if field.is_repeated else [value])
    if len(model.graph.input) != 1 or len(model.graph.output) != 1:
        raise ValueError('Unsupported ONNX input or output count')
    for entry, shape in ((model.graph.input[0], (1, 3, SIZE, SIZE)), (model.graph.output[0], OUTPUT)):
        tensor = entry.type.tensor_type
        dimensions = tensor.shape.dim
        if tensor.elem_type != onnx.TensorProto.FLOAT or tuple(
            dim.dim_value if dim.HasField('dim_value') else None for dim in dimensions
        ) != shape:
            raise ValueError('Unsupported ONNX tensor type or shape')
    onnx.checker.check_model(model)
    return model.graph.input[0].name, model.graph.output[0].name


def preprocess(frame: bytes, ref: FrameRef):
    if ref.width * ref.height > MAX_FRAME_PIXELS:
        raise ValueError('Frame exceeds pixel limit')
    with Image.open(BytesIO(frame), formats=['JPEG', 'PNG']) as image:
        expected = {'image/jpeg': 'JPEG', 'image/png': 'PNG'}[ref.content_type]
        if (image.format != expected or image.size != (ref.width, ref.height)
                or getattr(image, 'n_frames', 1) != 1):
            raise ValueError('Frame format or dimensions differ from request')
        gain = min(SIZE / ref.width, SIZE / ref.height)
        width, height = round(ref.width * gain), round(ref.height * gain)
        if not width or not height:
            raise ValueError('Unsupported frame aspect ratio')
        left, top = (SIZE - width) // 2, (SIZE - height) // 2
        resized = image.convert('RGB').resize((width, height), Image.Resampling.BILINEAR)
        canvas = Image.new('RGB', (SIZE, SIZE), (114, 114, 114))
        canvas.paste(resized, (left, top))
        tensor = np.ascontiguousarray(np.asarray(canvas, dtype=np.float32).transpose(2, 0, 1)[None] / 255)
    return tensor, gain, left, top


def suppress(boxes, classes, scores):
    order = np.argsort(-scores, kind='stable')
    area = np.prod(boxes[:, 2:] - boxes[:, :2], axis=1)
    while order.size:
        head, tail = order[0], order[1:]
        yield head
        intersection = np.prod(np.maximum(
            np.minimum(boxes[head, 2:], boxes[tail, 2:])
            - np.maximum(boxes[head, :2], boxes[tail, :2]), 0,
        ), axis=1)
        iou = intersection / (area[head] + area[tail] - intersection)
        order = tail[(classes[tail] != classes[head]) | (iou <= NMS_IOU)]


def detection(class_id, score, box):
    if not 0 <= class_id < len(LABELS):
        raise ValueError('Unknown model class')
    label = LABELS[class_id]
    color, suffix, kind = label.partition(' ')
    return Detection(
        original_class=label, class_key=kind if suffix else label,
        attributes={'color': color} if suffix else {},
        score=float(score), bbox_xyxy=tuple(map(float, box)),
    )


def decode(output, request, gain, left, top):
    from itertools import islice

    if output.shape != OUTPUT or output.dtype != np.float32 or not np.isfinite(output).all():
        raise ValueError('Malformed raw detector output')
    threshold = request.options.confidence_threshold
    if not isfinite(threshold):
        raise ValueError('Invalid confidence threshold')
    candidates = output[0].T
    scores = candidates[:, 4:].max(axis=1)
    if ((candidates[:, 4:] < 0) | (candidates[:, 4:] > 1)).any():
        raise ValueError('Invalid class confidence')
    candidates, scores = candidates[scores > threshold], scores[scores > threshold]
    # A float64 intermediate keeps arithmetic finite even for malformed large FP32 boxes.
    centers, sizes = candidates[:, :2].astype(np.float64), candidates[:, 2:4].astype(np.float64)
    if (sizes <= 0).any():
        raise ValueError('Invalid detection box size')
    boxes = np.concatenate((centers - sizes / 2, centers + sizes / 2), axis=1)
    if (boxes[:, 2:] <= boxes[:, :2]).any():
        raise ValueError('Invalid detection corners')
    classes = candidates[:, 4:].argmax(axis=1)
    result = []
    for index in islice(suppress(boxes, classes, scores), MAX_DETECTIONS):
        box = (boxes[index] - (left, top, left, top)) / gain
        box[::2] = box[::2].clip(0, request.frame.width)
        box[1::2] = box[1::2].clip(0, request.frame.height)
        if box[0] < box[2] and box[1] < box[3]:
            result.append(detection(int(classes[index]), scores[index], box))
    return result


@dataclass
class LoadedModel:
    session: ort.InferenceSession | None
    input_name: str
    output_name: str


class CpuRuntime:
    @contextmanager
    def load(self, artifact: bytes):
        input_name, output_name = validate_graph(artifact)
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        session = ort.InferenceSession(artifact, sess_options=options, providers=['CPUExecutionProvider'])
        session.disable_fallback()
        loaded = LoadedModel(session, input_name, output_name)
        del session
        try:
            yield loaded
        finally:
            loaded.session = None

    def infer(self, model: LoadedModel, frame: bytes, request: InferenceRequest) -> list[Detection]:
        if model.session is None:
            raise ValueError('Model session is closed')
        tensor, gain, left, top = preprocess(frame, request.frame)
        output, = model.session.run([model.output_name], {model.input_name: tensor})
        return decode(output, request, gain, left, top)


def factory() -> CpuRuntime:
    return CpuRuntime()
