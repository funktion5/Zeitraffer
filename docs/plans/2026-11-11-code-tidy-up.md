# Code tidy-up

Status: STARTED 2026-11-11. Julius asked for tidier code. Three steps, in this order, one at a time:
tests first, one topic per commit, `pytest` and `ruff` on the VPS after each (the Python pipeline is
stable: every step keeps behaviour identical).

## 1. Break the import cycle (storage_box.py): DONE 2026-11-11, waiting for pytest on the VPS

`frame_source.py` imports from `storage_filter.py` lazily in four places, because `storage_filter.py`
imports `images.py` and `images.py` imports `frame_source.py`. Move `StorageBox`, `parse_ls_output`,
`STORAGE_BOX_ENV` and `get_storage_box` (and what only they need) into `src/storage_box.py`. Then
`frame_source.py` imports it at the top and the lazy imports are gone. Done when: no function-level
`from src.storage_filter import` is left in `frame_source.py`, the suite is unchanged.

## 2. The long job runners

Measured 2026-11-11: `run_yearly_job` 183 lines, `main()` 175, `run_monthly_job` 157, `run_daily_job`
155, `run_weekly_job` 89. Read the monthly and yearly runners side by side first; extract only what
really is shared (the per-camera loop, the gate, the coverage check, the cleanup), one job at a time.
Do not merge for the sake of merging.

## 3. Bigger files, when next touched

`web/public/camera.php` (928 lines, a 175-line inline script with PHP values: move the script to a file
the way the settings pages did, passing the values as data attributes) and `src/images.py` (823 lines:
split by topic, for example scan, select, duplicates). Left alone until one of them is edited for
another reason.

## Not on the list (YAGNI)

Splitting `web/public/verpixelung.js` into modules, the 111-line `settingsScalarFields` (it is data),
more touch support for the Verpixelung editor.
