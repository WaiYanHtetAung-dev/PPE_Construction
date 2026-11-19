"""Capture detections from a disposable, signed Phase 2.5 worker endpoint."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

from app.contracts.inference import InferenceRequest, InferenceResponse
from inference_worker.auth import read_token
from inference_worker.contract import INFERENCE_PATH, LEASE_PATH, MAX_LEASE_SECONDS, LeaseRequest, ModelLease
from inference_worker.onnx_cpu import LABELS
from infra.onnx_export.corpus import APPROVAL, SHA256, load_corpus, read_sample
from infra.onnx_export.run_offline import EXPECTED


def local_origin(value, compose_host):
    origin = httpx.URL(value)
    if (origin.host not in ('127.0.0.1', '::1', compose_host)
            or origin.scheme not in ('http', 'https') or origin.path not in ('', '/')
            or origin.userinfo or origin.query or origin.fragment):
        raise ValueError('Use a disposable local service origin')
    return origin


def require_evidence(client, token, model_key, model_version, digest):
    query = LeaseRequest(model_key=model_key, model_version=model_version, nonce=uuid4())
    reply = client.post(LEASE_PATH, json=query.model_dump(mode='json'),
                        headers={'Authorization': 'Bearer ' + token})
    if reply.status_code != 200:
        raise ValueError('Disposable authority did not provide live evidence')
    lease = ModelLease.model_validate_json(reply.content)
    if ((lease.nonce, lease.model_key, lease.model_version, lease.artifact_sha256)
            != (query.nonce, model_key, model_version, digest)
            or not 0 < (lease.expires_at - lease.issued_at).total_seconds() <= MAX_LEASE_SECONDS
            or lease.expires_at <= datetime.now(timezone.utc)):
        raise ValueError('Disposable eligibility does not match the candidate digest')
    return lease.evidence()


def raw_detection(detection):
    class_id = LABELS.index(detection.original_class)
    expected_class = {3: 'person', 5: 'vest'}.get(class_id, 'helmet')
    expected_color = LABELS[class_id].split()[0] if expected_class == 'helmet' else None
    if detection.class_key != expected_class or detection.attributes.get('color') != expected_color:
        raise ValueError('Worker canonical class or color does not match label')
    return {'class_id': class_id, 'score': detection.score, 'bbox_xyxy': detection.bbox_xyxy}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('corpus_root', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--origin', required=True, help='Disposable loopback or inference-worker origin')
    parser.add_argument('--token-file', type=Path, required=True)
    parser.add_argument('--authority-origin', required=True)
    parser.add_argument('--authority-token-file', type=Path, required=True)
    parser.add_argument('--model-key', required=True)
    parser.add_argument('--model-version', required=True)
    parser.add_argument('--export-report', type=Path, required=True)
    parser.add_argument('--worker-approval', required=True)
    args = parser.parse_args()
    origin = local_origin(args.origin, 'inference-worker')
    authority_origin = local_origin(args.authority_origin, 'eligibility-authority')
    if (not APPROVAL.fullmatch(args.worker_approval) or args.worker_approval.startswith('REPLACE-')
            or any((p / '.git').exists() for p in args.output.resolve().parents)):
        parser.error('Provide the disposable worker approval record and output outside Git')
    report = json.loads(args.export_report.read_text(encoding='utf-8'))
    if (not SHA256.fullmatch(report['artifact_sha256']) or report['source_sha256'] != EXPECTED
            or report['versions']['ultralytics'] not in ('8.4.96', '8.4.102')):
        parser.error('Use a valid reviewed export report')
    corpus, corpus_digest = load_corpus(args.manifest, args.corpus_root)
    detections = {}
    ingress = read_token(str(args.token_file))
    authority_token = read_token(str(args.authority_token_file))
    if ingress == authority_token:
        parser.error('Use distinct disposable ingress and authority credentials')
    evidence = (authority_token, args.model_key, args.model_version, report['artifact_sha256'])
    transport = {'timeout': 20, 'follow_redirects': False, 'trust_env': False}
    with httpx.Client(base_url=origin, **transport) as client, httpx.Client(base_url=authority_origin, **transport) as authority:
        approved = require_evidence(authority, *evidence)
        for sample in corpus['samples']:
            read_sample(args.corpus_root, sample)
            ask = InferenceRequest(
                request_id=uuid4(), frame_id=sample['id'], model_key=args.model_key,
                model_version=args.model_version,
                frame={'object_key': 'frames/' + sample['file'], 'width': sample['width'],
                       'height': sample['height'],
                       'content_type': 'image/png' if sample['file'].endswith('.png') else 'image/jpeg'},
            )
            reply = client.post(INFERENCE_PATH, json=ask.model_dump(mode='json'), headers={
                'Authorization': 'Bearer ' + ingress,
            })
            if reply.status_code != 200:
                raise RuntimeError('Disposable worker did not return a successful verified inference')
            if require_evidence(authority, *evidence) != approved:
                raise ValueError('Eligibility evidence changed during parity capture')
            result = InferenceResponse.model_validate_json(reply.content)
            if (result.request_id, result.frame_id, result.model_key, result.model_version) != (
                ask.request_id, ask.frame_id, ask.model_key, ask.model_version,
            ):
                raise ValueError('Worker response identity mismatch')
            if any(d.bbox_xyxy[2] > sample['width'] or d.bbox_xyxy[3] > sample['height'] for d in result.detections):
                raise ValueError('Worker detection exceeds approved frame size')
            detections[sample['id']] = [raw_detection(d) for d in result.detections]
    with args.output.open('x', encoding='utf-8') as output:
        json.dump({'corpus_sha256': corpus_digest, 'mode': 'verified-worker',
                   'artifact_sha256': report['artifact_sha256'],
                   'verification_id': approved[-1],
                   'exporter_version': report['versions']['ultralytics'],
                   'worker_approval': args.worker_approval,
                   'model_key': args.model_key, 'model_version': args.model_version,
                   'samples': {row['id']: {'purpose': row['purpose'], 'aspect_ratio': row['aspect_ratio'],
                                          'width': row['width'], 'height': row['height']}
                               for row in corpus['samples']}, 'detections': detections}, output, indent=2)
        output.write('\n')


if __name__ == '__main__':
    main()
