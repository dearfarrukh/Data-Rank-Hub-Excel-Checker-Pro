from __future__ import annotations

import pandas as pd


def repeated_runs(values: list[float | None], threshold: int) -> list[dict]:
    runs: list[dict] = []
    start = 0

    while start < len(values):
        value = values[start]
        if value is None or pd.isna(value):
            start += 1
            continue

        end = start
        while end + 1 < len(values):
            nxt = values[end + 1]
            if nxt is None or pd.isna(nxt) or float(nxt) != float(value):
                break
            end += 1

        length = end - start + 1
        if length >= threshold:
            runs.append({
                "start_index": start,
                "end_index": end,
                "length": length,
                "value": float(value),
            })
        start = end + 1

    return runs
