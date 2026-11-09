"""Each invocation gets a new evidence directory to avoid stale passes."""

import json
from pathlib import Path


class Evidence:
    def __init__(self, directory: Path, redact=lambda value: value):
        self.root = Path(directory)
        self.root.mkdir(parents=True, exist_ok=False, mode=0o700)
        self.redact = redact

    def write(self, name: str, value):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        text = self.redact(json.dumps(value, indent=2, allow_nan=False)) + "\n"
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(target)
