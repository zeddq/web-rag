from __future__ import annotations

import hashlib
import os
from typing import Iterable


def safe_filename(url: str) -> str:
    """Create a safe filename from URL with a stable hash."""
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return f"{h}.txt"


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def batched(iterable: Iterable, n: int):
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= n:
            yield batch
            batch = []
    if batch:
        yield batch

