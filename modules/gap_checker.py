from __future__ import annotations

from dataclasses import dataclass

from modules.orientation import PeriodToken, parse_period


@dataclass(frozen=True)
class MissingRange:
    start_index: int
    end_index: int
    length: int
    label: str


def compress_missing_ranges(indices: list[int], period_columns: list) -> list[MissingRange]:
    if not indices:
        return []

    groups: list[list[int]] = []
    current = [indices[0]]
    for idx in indices[1:]:
        if idx == current[-1] + 1:
            current.append(idx)
        else:
            groups.append(current)
            current = [idx]
    groups.append(current)

    results: list[MissingRange] = []
    for group in groups:
        start, end = group[0], group[-1]
        if start == end:
            label = str(period_columns[start])
        else:
            label = f"{period_columns[start]} → {period_columns[end]}"
        results.append(MissingRange(start, end, len(group), label))
    return results


def _annual_expected(start: PeriodToken, end: PeriodToken) -> list[tuple[tuple[int, int, int], str]]:
    return [((year, 0, 0), str(year)) for year in range(start.key[0], end.key[0] + 1)]


def _monthly_expected(start: PeriodToken, end: PeriodToken) -> list[tuple[tuple[int, int, int], str]]:
    y, m = start.key[0], start.key[1]
    end_y, end_m = end.key[0], end.key[1]
    out = []
    while (y, m) <= (end_y, end_m):
        out.append(((y, m, 0), f"{y:04d}-{m:02d}"))
        m += 1
        if m == 13:
            y += 1
            m = 1
    return out


def _quarterly_expected(start: PeriodToken, end: PeriodToken) -> list[tuple[tuple[int, int, int], str]]:
    y, q = start.key[0], start.key[2]
    end_y, end_q = end.key[0], end.key[2]
    out = []
    while (y, q) <= (end_y, end_q):
        out.append(((y, 0, q), f"{y:04d} Q{q}"))
        q += 1
        if q == 5:
            y += 1
            q = 1
    return out


def expected_periods(period_columns: list) -> list[tuple[tuple[int, int, int], str]]:
    tokens = [parse_period(col) for col in period_columns]
    tokens = [token for token in tokens if token is not None]
    if not tokens:
        return []

    tokens = sorted(tokens, key=lambda t: t.key)
    frequencies = {token.frequency for token in tokens}
    if len(frequencies) != 1:
        return []

    frequency = tokens[0].frequency
    if frequency == "Annual":
        return _annual_expected(tokens[0], tokens[-1])
    if frequency == "Monthly":
        return _monthly_expected(tokens[0], tokens[-1])
    if frequency == "Quarterly":
        return _quarterly_expected(tokens[0], tokens[-1])
    return []
