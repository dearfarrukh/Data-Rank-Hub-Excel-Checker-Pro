# Data Rank Hub Excel Checker Pro

Fresh modular rebuild of the Data Rank Hub historical/ranking dataset checker.

## Stage 1

- Excel `.xlsx` / `.xls` upload
- CSV upload
- Sheet selection
- Automatic Checker-vs-AlienArt orientation detection
- Annual, monthly, quarterly period parsing
- Internal normalization to `Entity | Period...`
- Original orientation metadata retained for later export
- Automated orientation tests

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Test

```bash
pytest -q
```

## Deployment

Repository: `Data-Rank-Hub-Excel-Checker-Pro`  
Branch: `main`  
Main file: `app.py`
