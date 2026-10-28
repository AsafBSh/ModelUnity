"""Identify one local installation without exposing its path in the UI config."""
import hashlib
import os
from pathlib import Path


def instance_marker(root: Path) -> str:
    normalized = os.path.normcase(str(root.resolve()))
    token = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f'<meta name="modelunify-instance" content="{token}">'
