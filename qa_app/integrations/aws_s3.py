"""AWS S3: upload the full run folder (report, screenshots, Lighthouse) and share a link.

Credentials come from the standard AWS chain (env vars, ~/.aws profile, SSO, instance role) —
never stored by this app. If the bucket is served through CloudFront/static hosting, set
`public_base_url` so the report's images load; otherwise a 7-day presigned link to report.html is shared.
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

from ..models import RunResult

PRESIGN_SECONDS = 7 * 24 * 3600


def _client(cfg: dict):
    import boto3
    session = boto3.Session(profile_name=cfg.get("profile") or None, region_name=cfg.get("region") or None)
    return session.client("s3")


def publish(result: RunResult, cfg: dict, shared: dict, log) -> str:
    s3 = _client(cfg)
    run_dir = Path(result.output_dir)
    prefix = (cfg.get("prefix") or "").strip("/")
    key_prefix = f"{prefix}/{result.run_id}" if prefix else result.run_id
    count = 0
    for path in run_dir.rglob("*"):
        if path.is_file():
            key = f"{key_prefix}/{path.relative_to(run_dir).as_posix()}"
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            s3.upload_file(str(path), cfg["bucket"], key, ExtraArgs={"ContentType": ctype})
            count += 1
    report_key = f"{key_prefix}/report.html"
    if cfg.get("public_base_url"):
        shared["report_url"] = f"{cfg['public_base_url'].rstrip('/')}/{report_key}"
    else:
        shared["report_url"] = s3.generate_presigned_url(
            "get_object", Params={"Bucket": cfg["bucket"], "Key": report_key}, ExpiresIn=PRESIGN_SECONDS)
    return f"{count} files uploaded to s3://{cfg['bucket']}/{key_prefix}/"


def test_connection(cfg: dict) -> str:
    s3 = _client(cfg)
    s3.head_bucket(Bucket=cfg["bucket"])
    return f"Bucket {cfg['bucket']} is reachable"
