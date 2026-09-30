from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import pandas as pd

from modules.orientation import parse_period


@dataclass(frozen=True)
class LifecycleRule:
    canonical: str
    aliases: tuple[str, ...]
    valid_from: int | None
    valid_to: int | None
    protected_years: frozenset[int]
    notes: str = ""

    @property
    def names(self) -> tuple[str, ...]:
        return (self.canonical, *self.aliases)


def normalize_entity_name(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def load_lifecycle_rules(path: str | Path = "historical/entity_rules.txt") -> list[LifecycleRule]:
    path = Path(path)
    if not path.exists():
        return []

    rules: list[LifecycleRule] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|")]
        while len(parts) < 6:
            parts.append("")
        canonical, aliases_raw, valid_from_raw, valid_to_raw, protected_raw, notes = parts[:6]
        aliases = tuple(a.strip() for a in aliases_raw.split(";") if a.strip())
        valid_from = int(valid_from_raw) if valid_from_raw else None
        valid_to = int(valid_to_raw) if valid_to_raw else None
        protected_years = frozenset(int(y.strip()) for y in protected_raw.split(";") if y.strip())
        rules.append(LifecycleRule(canonical, aliases, valid_from, valid_to, protected_years, notes))
    return rules


def rule_lookup(rules: list[LifecycleRule]) -> dict[str, LifecycleRule]:
    lookup: dict[str, LifecycleRule] = {}
    for rule in rules:
        for name in rule.names:
            key = normalize_entity_name(name)
            if key:
                lookup[key] = rule
    return lookup


def period_year(period: object) -> int | None:
    token = parse_period(period)
    return int(token.key[0]) if token is not None else None


def classify_lifecycle(entity: object, period: object, lookup: dict[str, LifecycleRule]) -> tuple[str, LifecycleRule | None]:
    rule = lookup.get(normalize_entity_name(entity))
    year = period_year(period)
    if rule is None or year is None:
        return "UNRULED", rule
    if rule.valid_from is not None and year < rule.valid_from:
        return "EXPECTED_BEFORE_START", rule
    if rule.valid_to is not None and year > rule.valid_to:
        return "EXPECTED_AFTER_END", rule
    if year in rule.protected_years:
        return "PROTECTED_TRANSITION", rule
    return "ACTIVE", rule


def build_lifecycle_summary(
    df: pd.DataFrame,
    period_columns: list,
    numeric_matrix: pd.DataFrame,
    rules: list[LifecycleRule] | None = None,
) -> pd.DataFrame:
    rules = rules if rules is not None else load_lifecycle_rules()
    lookup = rule_lookup(rules)
    rows: list[dict] = []

    for row_index in df.index:
        entity = str(df.loc[row_index, "Entity"]).strip()
        matched_rule = lookup.get(normalize_entity_name(entity))
        expected = 0
        protected = 0
        for period in period_columns:
            if not pd.isna(numeric_matrix.loc[row_index, period]):
                continue
            status, _ = classify_lifecycle(entity, period, lookup)
            if status in {"EXPECTED_BEFORE_START", "EXPECTED_AFTER_END"}:
                expected += 1
            elif status == "PROTECTED_TRANSITION":
                protected += 1
        if matched_rule is not None or expected or protected:
            rows.append({
                "Entity": entity,
                "Rule": matched_rule.canonical if matched_rule else "",
                "Valid From": matched_rule.valid_from if matched_rule else None,
                "Valid To": matched_rule.valid_to if matched_rule else None,
                "Expected Historical Blanks": expected,
                "Protected Transition Blanks": protected,
                "Notes": matched_rule.notes if matched_rule else "",
            })

    return pd.DataFrame(rows, columns=[
        "Entity", "Rule", "Valid From", "Valid To", "Expected Historical Blanks",
        "Protected Transition Blanks", "Notes",
    ])
