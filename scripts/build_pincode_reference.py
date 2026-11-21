#!/usr/bin/env python
"""Build the committed India pincode reference file from the GeoNames dump.

Input is the GeoNames postal-code extract for India (`IN.txt` inside
https://download.geonames.org/export/zip/IN.zip, CC BY 4.0; see
`apps/api/app/data/SOURCES.md`). It has one row per post office: about 155k
rows for about 19k pincodes. The output has exactly one row per pincode:

    pincode,area,district,state,latitude,longitude

Normalisation (recorded in SOURCES.md, which CC BY 4.0 asks for):

- only `IN` rows whose code is a valid Indian pincode (six digits, first 1-9);
- state: the state most of the pincode's offices are in (ties: alphabetical);
  district: the most common district within that state;
- area: the head-office / GPO name with its suffix removed, else an office
  named like its sub-district, else the most common sub-district, else the
  first office name alphabetically;
- centroid: the mean of the coordinates inside India's bounding box, using
  only the most precise accuracy class present for that pincode (GeoNames'
  class 1 is an estimate from neighbouring codes). A pincode with no usable
  coordinate keeps its place name and gets empty coordinates;
- text is trimmed, control and U+FFFD characters are removed, and every field
  is length-capped to the database column size.

The downloaded file is untrusted input: it is parsed as plain tab-separated
text, never executed, and every value is validated before it is written.
Run with an isolated interpreter and pass the paths as arguments, e.g.

    python -I scripts/build_pincode_reference.py <dir>/IN.txt \
        apps/api/app/data/pincodes.csv.gz

The output is deterministic (sorted rows, gzip with no name and mtime 0), so a
re-run on the same input reproduces the same bytes.
"""

from __future__ import annotations

import argparse
import collections
import csv
import gzip
import io
import re
import sys
from pathlib import Path

PINCODE_RE = re.compile(r"^[1-9][0-9]{5}$")
# Generous India bounding box (mainland, Andaman & Nicobar, Lakshadweep, Ladakh).
LAT_MIN, LAT_MAX = 6.0, 37.6
LON_MIN, LON_MAX = 68.0, 97.6
AREA_MAX = 120
DISTRICT_MAX = 80
STATE_MAX = 80
_HEAD_OFFICE = re.compile(r"\s+(G\.?P\.?O\.?|H\.?O\.?)$", re.IGNORECASE)
_UNWANTED = re.compile(r"[\x00-\x1f\x7f�]")
_SPACES = re.compile(r"\s+")


def clean(value: str, limit: int) -> str:
    value = _SPACES.sub(" ", _UNWANTED.sub("", value)).strip()
    return value[:limit].rstrip()


def _coordinate(lat: str, lon: str) -> tuple[float, float] | None:
    try:
        la, lo = float(lat), float(lon)
    except ValueError:
        return None
    if not (LAT_MIN <= la <= LAT_MAX and LON_MIN <= lo <= LON_MAX):
        return None
    return la, lo


def _accuracy(value: str) -> int:
    return int(value) if value.isdigit() else 0


def _most_common(values: list[str]) -> str:
    counts = collections.Counter(values)
    best = max(counts.values())
    return sorted(value for value, count in counts.items() if count == best)[0]


def _area(offices: list[tuple[str, str]]) -> str:
    """offices: (office name, sub-district) pairs, already cleaned."""
    for name, _ in sorted(offices):
        if _HEAD_OFFICE.search(name):
            stripped = _HEAD_OFFICE.sub("", name).strip()
            if stripped:
                return stripped
    sub_districts = {
        sub.casefold() for _, sub in offices if sub and sub.upper() != "NA"
    }
    for name, _ in sorted(offices):
        if name.casefold() in sub_districts:
            return name
    usable = [sub for _, sub in offices if sub and sub.upper() != "NA"]
    if usable:
        return _most_common(usable)
    return sorted(name for name, _ in offices)[0]


def build(source: Path) -> list[tuple[str, str, str, str, str, str]]:
    groups: dict[str, list[list[str]]] = collections.defaultdict(list)
    with source.open(encoding="utf-8", errors="replace", newline="") as handle:
        for record in csv.reader(handle, delimiter="\t", quoting=csv.QUOTE_NONE):
            if len(record) != 12 or record[0] != "IN":
                continue
            pincode = record[1].strip()
            if not PINCODE_RE.match(pincode):
                continue
            groups[pincode].append(record)

    rows = []
    for pincode in sorted(groups):
        records = groups[pincode]
        state = _most_common(
            [clean(r[3], STATE_MAX) for r in records if clean(r[3], STATE_MAX)] or [""]
        )
        in_state = [r for r in records if clean(r[3], STATE_MAX) == state]
        district = _most_common(
            [clean(r[5], DISTRICT_MAX) for r in in_state if clean(r[5], DISTRICT_MAX)]
            or [""]
        )
        offices = [
            (clean(r[2], AREA_MAX), clean(r[7], AREA_MAX))
            for r in in_state
            if clean(r[2], AREA_MAX)
        ]
        if not state or not district or not offices:
            continue
        area = _area(offices)

        located = [
            (_accuracy(r[11]), point)
            for r in records
            if (point := _coordinate(r[9], r[10])) is not None
        ]
        if located:
            best = max(accuracy for accuracy, _ in located)
            points = [point for accuracy, point in located if accuracy == best]
            latitude = f"{sum(p[0] for p in points) / len(points):.4f}"
            longitude = f"{sum(p[1] for p in points) / len(points):.4f}"
        else:
            latitude = longitude = ""
        rows.append((pincode, area, district, state, latitude, longitude))
    return rows


def write(rows: list[tuple[str, ...]], destination: Path) -> bytes:
    text = io.StringIO(newline="")
    writer = csv.writer(text, lineterminator="\n")
    writer.writerow(("pincode", "area", "district", "state", "latitude", "longitude"))
    writer.writerows(rows)
    raw = io.BytesIO()
    with gzip.GzipFile(
        filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0
    ) as gz:
        gz.write(text.getvalue().encode("utf-8"))
    data = raw.getvalue()
    destination.write_bytes(data)
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="GeoNames IN.txt (tab-separated)")
    parser.add_argument("destination", type=Path, help="output .csv.gz")
    args = parser.parse_args(argv)
    rows = build(args.source)
    data = write(rows, args.destination)
    located = sum(1 for row in rows if row[4])
    print(f"pincodes={len(rows)} with_centroid={located} bytes={len(data)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
