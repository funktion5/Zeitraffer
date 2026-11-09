# Idea: a progress bar for manual video jobs in the web UI

Status: **IDEA, DRAFT 2026-11-05. Nothing here is decided, planned or started.** It is not mandatory;
it would only be a nicety for the colleagues who start videos from the web UI. Julius's wish: write it
down for later. The manual Weekly blur comes first.

## Why

A manual Daily, Monthly, Yearly (soon Weekly) of a blur camera can take 30 to 60 minutes, because
its frames are blurred on the Storage Box first
([blur-backfill plan](done/2026-11-05-blur-backfill-for-long-videos.md)). The camera page only says
"... läuft. Ein neues Video kann erst danach gestartet werden." A colleague cannot tell whether
the job is at the start or nearly done.

## How the page learns the status today

- `web/src/components/job-watcher.php` polls `web/public/job-status.php` every 5 seconds and gets
  only `running`, `completed` or `failed` (plus a German reason on failure).
- `scripts/web/timelapse-web-worker` sends the job's log (stderr of `src.main`) to a temp file that
  is read once, at the end, to find the failure reason. While the job runs the server knows nothing
  about its progress.

## The idea (Julius, 2026-11-05)

One bar with a fixed weighting:

| Part of the bar | What it stands for |
| --- | --- |
| 0 to 5 % | Fetching and preparation: it shows 0 % until the first blur line appears, then 5 %. |
| 5 to 95 % | The blur: bar % = 5 + 0.9 x (blur %), so 0.9 % of the bar is 1 % of the blur. |
| 95 to 100 % | Fetching the blurred frames again and building the video; it stays at 95 % until the job is `completed`, then 100 %. |

The weighting is cosmetic and an approximation (the Weekly scans seven days one by one, so its first
part is longer than 5 % of the real time; the last part was never timed). Without anything to blur
(all frames already confirmed, or a camera outside `privacy.blur_cameras`) there is no total, so the
page keeps today's text line and shows no bar.

## What it would take

1. **Engine:** a frame that comes out clean writes NO log line today (only blurred frames log
   "Backed up" and "Replaced"; the clean count appears in a summary at the end of the round). On a mostly
   clean camera such as SLSV a bar built on the current log would hardly move and then jump. It needs
   one progress line per processed frame in `blur_frames`, e.g. `[cam] Blur progress: 137 of 313`,
   with a test. The total already exists: `[cam] Blur: N frames, X already confirmed, Y to blur`.
2. **Worker** (`scripts/web/timelapse-web-worker`, a root-owned wrapper): keep the log in
   `state/web-jobs/<id>.log` instead of a temp file, so the status endpoint can read it. The wrapper
   has to be reinstalled by hand on the VPS, like the other wrappers.
3. **`job-status.php`:** stays read-only; count progress from that log and return
   `progress: {done, total}` while `running`.
4. **Page:** a native `<progress>` element with a German text ("Verpixelt 137 von 360"), a small CSS
   rule and an accessible label (BFSG, WCAG 2.2 AA); an unchanged text is not rewritten, so screen
   readers do not announce every poll.
5. **Tests:** the project's structural PHP tests plus the engine test from step 1.

Estimate (not measured): a moderate task, comparable to the web note and the German failure
reasons of 2026-11-05: several files, about 10 tests, plus the manual wrapper step.

## Open

- Whether it is worth doing at all; it only helps people waiting for a long blur job.
- Whether the bar should also cover jobs without a blur (Daily of a plain camera): they are short, so
  probably not.
- The log of a finished job would stay in `state/web-jobs/`: check the cleanup of that folder when
  this is built.
