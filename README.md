# Data Rank Hub Excel Checker Pro

Professional modular Streamlit checker for historical ranking datasets.

## Main workflow

`UPLOAD → CHECK → REVIEW BY COUNTRY → FIX → RECHECK → DOWNLOAD`

## V1 Pro features

- Excel / CSV upload
- Checker and AlienArt orientation auto-detection
- Annual / monthly / quarterly period support
- Core structural and numeric checks
- Period-by-period Top-N risk engine
- Historical lifecycle protection
- Country-by-country review workspace
- Manual correction
- Keep / Ignore
- Force Correct with documented reasons and range scope
- Safe internal Series Fill
- One-button `AUTO FILL ALL SAFE GAPS`
- Corrected Excel export in original orientation
- Audit report + change log

Historical rules never blindly replace blanks with zero and never automatically copy predecessor values into successor-country series.

## V1.1 coverage review
- Detects unclassified leading blanks as **Start Year Candidate**.
- Detects unclassified trailing blanks as **End Year Candidate**.
- Shows the suggested first/last populated period and value.
- Known lifecycle ranges and existing Force Correct ranges are excluded.
- One-click **Confirm Start Year / Confirm End Year** creates a documented rule; it does not invent or copy values.
- Start/End candidates have their own sidebar view and do not inflate ordinary Review counts.
