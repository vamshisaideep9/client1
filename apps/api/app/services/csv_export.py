"""Safe CSV serialization shared by staff exports."""

import csv
import io
from collections.abc import Generator

_FORMULA_LEAD_CHARS = ("=", "+", "-", "@", "\t", "\r")


def csv_cell(value: object) -> str:
    """Force spreadsheet formula-leading values to be treated as text."""
    content = str(value)
    return "'" + content if content and content[0] in _FORMULA_LEAD_CHARS else content


def csv_chunks(rows: list[dict], header: list[str]) -> Generator[bytes, None, None]:
    yield "\ufeff".encode()  # Excel needs the UTF-8 BOM for non-ASCII names.
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    yield buffer.getvalue().encode()
    for row in rows:
        buffer.seek(0)
        buffer.truncate()
        writer.writerow([csv_cell(row.get(field, "")) for field in header])
        yield buffer.getvalue().encode()
