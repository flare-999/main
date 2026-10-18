from __future__ import annotations

from pathlib import Path
import json
from typing import Any

_SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"



def _canonicalize_hex(value: str) -> str:
    """Canonicalize a hex string to lowercase, stripped, and validate for proper format."""
    if not isinstance(value, str):
        return ""
    value = value.lower().strip()
    try:
        int(value, 16)
    except ValueError:
        return ""
    return value


def _canonicalize_hex_length(value: str, expected_len: int) -> str | None:
    """Canonicalize and validate hex string length."""
    canonical = _canonicalize_hex(value)
    if not canonical:
        return None
    if len(canonical) != expected_len:
        return None
    return canonical


def discover_schemas() -> list[dict[str, Any]]:
    if not _SCHEMA_DIR.is_dir():
        return []
    schemas: list[dict[str, Any]] = []
    for path in sorted(_SCHEMA_DIR.glob("*.json")):
        try:
            with open(path) as f:
                data = json.load(f)
            if not isinstance(data, dict):
                continue
            schemas.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return schemas


def resolve_schema(schema_hash: str) -> dict[str, Any] | None:
    target = _canonicalize_hex(schema_hash)
    if not target:
        return None
    for schema in discover_schemas():
        candidate = _canonicalize_hex(schema.get("schemaHash", ""))
        if candidate == target:
            return schema
    return None


def validate_selective_disclosure_input(
    body: dict[str, Any],
) -> str | None:
    required = {"schemaHash", "publicInputs", "proof"}
    missing = required - set(body.keys())
    if missing:
        return f"missing required field: {sorted(missing)[0]}"

    schema_hash = _canonicalize_hex_length(body.get("schemaHash", ""), 64)
    if not schema_hash:
        return "schemaHash must be a 64-char hex string"

    public_inputs = _canonicalize_hex_length(body.get("publicInputs", ""), 704)
    if not public_inputs:
        return "publicInputs must be a 704-char hex string (352 bytes)"

    proof = _canonicalize_hex(body.get("proof", ""))
    if not proof or len(proof) < 2:
        return "proof must be a non-empty hex string"

    return None


