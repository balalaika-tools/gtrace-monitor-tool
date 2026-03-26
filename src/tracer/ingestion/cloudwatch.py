from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from tracer.core.logging import get_logger
from tracer.core.settings import get_settings

logger = get_logger(__name__)


def _get_client():
    settings = get_settings()
    kwargs = {"region_name": settings.aws_default_region}
    if settings.aws_access_key_id:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        kwargs["aws_session_token"] = settings.aws_session_token
    return boto3.client("logs", **kwargs)


class FetchResult:
    """Result of a CloudWatch fetch."""

    def __init__(self, bulk_file: str, event_count: int, truncated: bool = False, limit: int = 0):
        self.bulk_file = bulk_file
        self.event_count = event_count
        self.truncated = truncated
        self.limit = limit


def fetch_cloudwatch_logs(
    start_time: datetime,
    end_time: datetime,
    store_dir: str,
    *,
    progress_callback=None,
) -> FetchResult:
    """Fetch CloudWatch logs and stream them directly to a bulk JSONL file on disk.

    Pages are written to disk as they arrive — only one page (~10K events)
    is held in memory at a time.
    """
    settings = get_settings()
    client = _get_client()
    max_events = settings.max_log_events

    start_ms = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000)

    bulk_file = str(Path(store_dir) / "_bulk.jsonl")

    logger.info(
        "Fetching CloudWatch logs: group=%s, filter=%s, range=%s to %s, max=%d",
        settings.log_group_name,
        settings.log_filter_pattern,
        start_time.isoformat(),
        end_time.isoformat(),
        max_events,
    )

    next_token = None
    page = 0
    event_count = 0
    truncated = False

    try:
        with open(bulk_file, "w") as f:
            while True:
                kwargs = {
                    "logGroupName": settings.log_group_name,
                    "startTime": start_ms,
                    "endTime": end_ms,
                    "filterPattern": settings.log_filter_pattern,
                    "limit": 10000,
                }
                if next_token:
                    kwargs["nextToken"] = next_token

                response = client.filter_log_events(**kwargs)

                for event in response.get("events", []):
                    msg = event.get("message", "").strip()
                    if msg:
                        f.write(msg + "\n")
                        event_count += 1

                        if event_count >= max_events:
                            truncated = True
                            break

                page += 1
                if progress_callback:
                    progress_callback(event_count, page)

                if truncated:
                    logger.warning("Reached MAX_LOG_EVENTS limit (%d). Stopping fetch.", max_events)
                    break

                next_token = response.get("nextToken")
                if not next_token:
                    break

                # Avoid API throttling
                time.sleep(0.2)

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        logger.error("CloudWatch API error: %s — %s", error_code, error_msg)
        raise RuntimeError(f"CloudWatch error: {error_code} — {error_msg}") from e

    logger.info("Fetched %d log events across %d pages (truncated=%s)", event_count, page, truncated)
    return FetchResult(bulk_file=bulk_file, event_count=event_count, truncated=truncated, limit=max_events)


def copy_local_file_to_store(file_path: str, store_dir: str) -> str:
    """Copy a local log file into the store directory as _bulk.jsonl."""
    import shutil

    bulk_file = str(Path(store_dir) / "_bulk.jsonl")
    shutil.copy2(file_path, bulk_file)
    logger.info("Copied local file %s to %s", file_path, bulk_file)
    return bulk_file


def write_upload_to_store(content: str, store_dir: str) -> str:
    """Write uploaded file content to the store directory as _bulk.jsonl."""
    bulk_file = str(Path(store_dir) / "_bulk.jsonl")
    Path(bulk_file).write_text(content)
    logger.info("Wrote uploaded content to %s", bulk_file)
    return bulk_file
