
## V1.4 Final UI Polish
- Core checker/ranking logic unchanged from V1.3.
- Main navigation now labels the selected workspace as **Top N Issues** (not countries).
- Shows how many selected Top-N countries currently need review.
- Status card emphasizes **Top-N Safety** instead of a truncated generic status.
- Advanced/other-country wording is clearer and less cluttered.
- Technical details remain hidden under Advanced Details.

# Data Rank Hub Excel Checker Pro — V1.3 Ever Top-N Workspace

Main workflow rule:

- Choose Top 10, Top 12, Top 15, or Custom Top N.
- If a country/entity enters that Top N in **any observed period**, **all of its unresolved issues stay in the main workspace**.
- This includes start/end coverage review, missing values, jumps, repeated values, zeros, invalid values, and Top-N risk.
- Countries that never enter the selected Top N are moved to **Advanced: Other Countries**.
- Historical expected blanks remain protected and are not treated as errors.
- Safe Fill is split so safe gaps for selected Top-N countries remain in the main workflow.

Main file: `app.py`
Branch: `main`
