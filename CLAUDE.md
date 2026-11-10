## Checks

Before saying a change is done, run the same checks as CI (`.github/workflows/ci.yml`) from this folder and fix any failure:

```
.venv/bin/python -m compileall -q bot.py acquire.py notion.py ledger.py watchdog.py doctor.py
ruff check --no-cache .
.venv/bin/python tests/test_pipeline.py
.venv/bin/python tests/test_cards.py
shellcheck ctl.sh install.sh
```

The tests need the project's packages. On Netcup (`~/saved-to-notes`) `.venv` has them; on the laptop create it once with `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt 'ruff==0.9.10'` (CI pins ruff 0.9.10). On 2026-11-09 compile and both test files passed on Netcup; shellcheck still flags `install.sh`, which keeps CI red. Keep CI green: a red check nobody fixes stops being a check.
