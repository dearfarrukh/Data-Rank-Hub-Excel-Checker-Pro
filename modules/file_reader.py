from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

import pandas as pd


SUPPORTED_EXTENSIONS = {".xlsx", ".xls", ".csv"}


@dataclass
class LoadedTable:
    dataframe: pd.DataFrame
    filename: str
    extension: str
    sheet_name: str | None


def _bytes_from_source(source: bytes | bytearray | BinaryIO) -> bytes:
    if isinstance(source, (bytes, bytearray)):
        return bytes(source)
    if hasattr(source, "getvalue"):
        return source.getvalue()
    if hasattr(source, "read"):
        current = source.tell() if hasattr(source, "tell") else None
        data = source.read()
        if current is not None and hasattr(source, "seek"):
            source.seek(current)
        return data
    raise TypeError("Unsupported file source.")


def extension_from_filename(filename: str) -> str:
    return Path(filename).suffix.lower()


def validate_extension(filename: str) -> str:
    ext = extension_from_filename(filename)
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError("Supported files: .xlsx, .xls, .csv")
    return ext


def get_sheet_names(source: bytes | bytearray | BinaryIO, filename: str) -> list[str]:
    ext = validate_extension(filename)
    if ext == ".csv":
        return []
    data = _bytes_from_source(source)
    with pd.ExcelFile(BytesIO(data)) as book:
        return list(book.sheet_names)


def read_table(
    source: bytes | bytearray | BinaryIO,
    filename: str,
    sheet_name: str | None = None,
) -> LoadedTable:
    ext = validate_extension(filename)
    data = _bytes_from_source(source)

    if ext == ".csv":
        df = pd.read_csv(BytesIO(data))
        return LoadedTable(df, filename, ext, None)

    with pd.ExcelFile(BytesIO(data)) as book:
        chosen = sheet_name or book.sheet_names[0]
        if chosen not in book.sheet_names:
            raise ValueError(f"Sheet '{chosen}' not found in workbook.")
        df = pd.read_excel(book, sheet_name=chosen)
    return LoadedTable(df, filename, ext, chosen)
