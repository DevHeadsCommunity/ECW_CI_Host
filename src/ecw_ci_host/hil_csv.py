"""Frontend-compatible physical-value CSV import and HIL word encoding."""

from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path
import re

PROFILES = Path(__file__).resolve().parent / "hil_profiles"
ADDRESS_LIMIT = 0x3F00
FORMATS = {"uint16": (16, 0, 65535), "int16": (16, -32768, 32767),
           "int32": (32, -2147483648, 2147483647)}
SAMPLE_HEADERS = {"#", "sample", "samples", "index", "n", "no"}
DECIMAL = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$", re.I)


def sensor_profile(name: str) -> dict:
    for path in sorted(PROFILES.glob("*.json")):
        profile = json.loads(path.read_text(encoding="utf-8"))
        if re.search(profile["match"], name, re.I):
            return profile
    raise ValueError(f"No frontend CSV encoding is defined for HIL sensor {name!r}.")


def decimal(cell: str) -> float | None:
    text = cell.strip().replace("−", "-")
    if re.fullmatch(r"[+-]?\d+,\d+", text):
        text = text.replace(",", ".")
    if not DECIMAL.fullmatch(text):
        return None
    value = float(text)
    return value if math.isfinite(value) else None


def header(cell: str) -> str:
    text = cell.strip().lower()
    return "#" if text == "#" else re.sub(r"[^a-z0-9]", "", text)


def channel_matches(name: str, channel: dict) -> bool:
    names = [channel["id"], channel["csvHeader"], *channel.get("headerAliases", [])]
    return any(name == alias or (len(alias) >= 3 and alias in name)
               for alias in map(header, names))


def encoded_words(cell: str, channel: dict) -> list[int]:
    encoding = channel["encoding"]
    bits, minimum, maximum = FORMATS[encoding["format"]]
    if not cell.strip():
        return [0] * (bits // 16)
    value = decimal(cell)
    if value is None:
        raise ValueError(f"{channel['label']}: {cell!r} is not a finite number")
    if not channel["min"] <= value <= channel["max"]:
        raise ValueError(f"{channel['label']}: {value} is outside "
                         f"{channel['min']} … {channel['max']} {channel['unit']}")
    scale = encoding.get("scale")
    if scale is None:
        scale = 2 ** (bits - 1) / encoding["fullScale"]
    # Same as frontend Math.round(Number(((value + offset) * scale).toPrecision(12))).
    raw = math.floor(float(format((value + encoding.get("offset", 0)) * scale, ".12g")) + 0.5)
    if not minimum <= raw <= maximum:
        if not encoding.get("saturate", False):
            raise ValueError(f"{channel['label']}: encoded value does not fit {encoding['format']}")
        raw = min(maximum, max(minimum, raw))
    unsigned = raw % (1 << bits)
    return [(unsigned >> shift) & 0xFFFF for shift in range(0, bits, 16)]


def read_csv(path: Path, profile: dict) -> tuple[list[int], int]:
    text = path.read_text(encoding="utf-8-sig")
    first = next((line for line in text.splitlines() if line.strip()), "")
    delimiter = "\t" if "\t" in first else ";" if ";" in first else ","
    cells = [row for row in csv.reader(io.StringIO(text), delimiter=delimiter, strict=True)
             if any(cell.strip() for cell in row)]
    channels = profile["channels"]
    count = len(channels)
    columns = list(range(count))
    if cells and any(cell.strip() and decimal(cell) is None for cell in cells[0]):
        headings = [header(cell) for cell in cells.pop(0)]
        mapped = [-1] * count
        sample_column = -1
        for index, name in enumerate(headings):
            if name in SAMPLE_HEADERS:
                if sample_column == -1:
                    sample_column = index
                continue
            for c, channel in enumerate(channels):
                if mapped[c] == -1 and channel_matches(name, channel):
                    mapped[c] = index
                    break
        if any(index != -1 for index in mapped):
            columns = mapped
        elif sample_column == 0 or len(headings) > count:
            columns = list(range(1, count + 1))
    elif any(len(row) > count for row in cells):
        columns = list(range(1, count + 1))
    rows = [[row[index].strip() if 0 <= index < len(row) else "" for index in columns]
            for row in cells]
    while rows and not any(rows[-1]):
        rows.pop()
    if not rows:
        raise ValueError("HIL CSV contains no sensor values.")
    words_per_sample = sum(FORMATS[c["encoding"]["format"]][0] // 16 for c in channels)
    max_samples = ADDRESS_LIMIT // words_per_sample
    if len(rows) > max_samples:
        raise ValueError(f"HIL CSV has {len(rows)} samples; {profile['label']} supports {max_samples}.")
    words = []
    for sample, row in enumerate(rows):
        for cell, channel in zip(row, channels):
            try:
                words.extend(encoded_words(cell, channel))
            except ValueError as error:
                raise ValueError(f"HIL CSV sample {sample}: {error}") from None
    return words, len(rows)
