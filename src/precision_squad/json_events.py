"""JSON event extraction utilities."""

from __future__ import annotations

import json


def extract_json_events(stdout: str) -> list[dict]:
    """Extract JSON objects from NDJSON output.

    Parses each line of stdout, looking for lines that start with '{'.
    Lines that are valid JSON dicts are collected into the result list.
    Non-JSON lines and malformed JSON lines are silently skipped.

    Args:
        stdout: Raw stdout text, typically from a subprocess or LLM response.

    Returns:
        List of parsed JSON dicts in order of appearance.
    """
    events: list[dict] = []
    for line in stdout.splitlines():
        text = line.strip()
        if not text.startswith("{"):
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events
