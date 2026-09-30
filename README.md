# Data Rank Hub Excel Checker Pro

Fresh modular rebuild of the Data Rank Hub historical/ranking dataset checker.

## Stage 4

- Excel `.xlsx` / `.xls` and CSV upload
- Checker-format and AlienArt-format orientation detection
- Annual / monthly / quarterly period parsing
- V10 core structural and numeric checks
- Period-by-period Top-N risk engine
- Historical lifecycle protection from configurable rules
- Clear user-facing problem table with Entity, Period, Problem, Why Flagged, and What To Do
- Separate Core Data Status and Top-N Ranking Safety
- Historical expected/protected blanks kept out of ordinary missing-data risk
- Original orientation remembered for future corrected-file export

## Historical policy

Historical lifecycle rules are stored in `historical/entity_rules.txt`. They are conservative and configurable. They never merge entities, invent values, or replace blanks with zero.

## Next stage

Stage 5 adds previewed **AUTO FILL ALL SAFE GAPS** with audit logging and protected-transition exclusions.
