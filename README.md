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
