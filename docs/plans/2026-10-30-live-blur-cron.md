# Plan: the live blur round in cron on the VPS

Status: DRAFT 2026-10-30, **nothing in here is decided yet**; it records the discussion and Claude's
recommendation. Nothing has been installed. It follows the go-live of the nightly lines
(docs/vps.md); the live round is a separate, later step.

## Goal

New camera images on the Storage Box are pixelated within about a minute of arriving (people and
number plates, `src/privacy/blur_box.py`, [verpixelung-box.md](../verpixelung-box.md)). Best effort:
the website's image fetcher is outside our control, so a rare unblurred pick-up is accepted
(Julius, 2026-10-21 and 2026-10-22).

## Why not a folder watcher (checked 2026-10-30)

- The Storage Box offers SFTP/SCP on port 22 and, on port 23, rsync, BorgBackup and a fixed list of
  shell commands (`ls`, `stat`, `cp`, `mv`, `rm`, `cat`, `grep`, hash tools, ...). Uploaded scripts
  cannot be executed, so nothing can run on the box and watch it. No webhook or event feature
  exists. Sources: Hetzner docs, "Access with SSH/rsync/BorgBackup" and "Access with SFTP/SCP".
- Linux file watching (`inotify`) only sees changes made on the machine it runs on, so a watcher on
  the VPS would not see uploads that reach the box from the cameras.
- Every method therefore asks the box what is new. Only the interval and the mechanism can change.

## Proposal (discussed 2026-10-30, not decided)

- **Mechanism A: cron, one round per minute** (Julius leaned this way): Already built and hand-verified on the VPS
  (BlurTest: backup, upload, swap). Restart-safe, one lock (`state/privacy-blur.lock`), no new
  infrastructure. The documented earlier idea of `*/5` is dropped in favour of every minute.
- **Daytime only** (Julius leaned this way): hours 05 to 22, no night rounds. The job already records night images without
  touching them, so the 02:00 catch-up still covers anything missed. Local time on the VPS is
  CET/CEST (checked: the file times show +0100); the window covers sunrise minus the 90 minute
  buffer in summer and sunset plus the buffer in winter.
- **Not now:** a loop inside each cron run (option B, a small `--run-for` and `--interval` option)
  and a permanent systemd service (option C). Revisit B only if the measured delay matters.

## The cron line (Julius pastes it; Claude never installs a crontab)

```cron
* 5-22 * * * cd <projektpfad> && export TIMELAPSE_STORAGE_BOX=<ssh-alias> && timeout -k 10 300 .venv/bin/python3 -m src.privacy.blur_box --all-blur-cameras
```

No `flock` is needed: the job takes its own lock (a kernel `flock`, released when the process ends,
even on a kill) and skips the round while another one runs, so cron can fire every minute without
rounds piling up. The nightly line (02:00, `--catch-up` under the shared run lock) uses the same job
lock, so the two can never write at the same time.

**Proposed cap of 5 minutes (Julius suggested it, not final):** `timeout -k 10 300` kills a stuck round after 5 minutes
at most (then 10 s more for a hard kill). Cameras upload every 10 to 15 minutes and the website
picks up every 5, so a round that runs longer than 5 minutes is a defect. A normal round is far
shorter (a backlog does about 4 images per camera in 40 s budgets). Every access has its own limit
(ssh command 30 s, scp 120 s, detector 120 s, ffmpeg 120 s), but those add up per image to around 10
minutes in the worst case (estimate), so the outer cap is the only absolute limit. A kill is safe by
design: the state file is written before the swap (`replacing`) and the next round finishes it. The
02:00 catch-up line keeps its own 45-minute budget per camera and gets no such cap.

## What to expect

- Delay from upload to the pixelated image: the 15 s settle time plus up to 60 s until the next
  round plus about 10 to 15 s of work, so roughly 90 s at worst and about 60 s on average (estimate
  from the Pi measurements in verpixelung-box.md; the VPS is unmeasured).
- Load: SLSV and Scheunenviertel produce about one image every 4 minutes together; an idle round is
  a Python start and two listings. Log growth: two summary lines per round, about 2,000 a day.

## The pick-up side (open: decision after the weekend)

The chain is: the camera uploads, the blur cron finds the image and pixelates it, the website's
pick-up cron (every 5 minutes, on the transfer host) takes it. Time after the camera finishes an
upload (estimates from the Pi measurements; the VPS is unmeasured):

| Step | Time |
|---|---|
| the job treats the file as finished (15 s unchanged) | 15 s |
| wait for the next cron minute | 0 to 60 s |
| list, fetch, detect, back up, swap | about 15 s |
| **typical: image pixelated** | **about 30 to 90 s** |
| another camera ahead in the same round (40 s budget each) | up to about 170 s |
| a stuck round, cut off at 300 s, then the next minute | up to about 6 to 7 min |

Scheunenviertel uploads every 15 minutes (:14:56, :29:56, :44:56, :59:56 by its file names), SLSV
every 10. The swap is atomic: a fetcher gets either the original or the pixelated file, never half
of one, but nothing tells it which. A pick-up job that runs on its own schedule and takes
everything can therefore hit the window of about 90 s (roughly one image in five or six, assuming
random timing and a 5 minute cycle; an estimate). No setting on our side closes that window.

**The guarantee has to come from the pick-up job:** take only images whose file time on the box is
at least N minutes old. N = 3 covers the normal chain with margin (also what verpixelung-box.md
suggests), N = 4 is the recommended value with a little more room, N = 7 would also cover a stuck
round. It costs nothing visible: uploads come every 10 to 15 minutes. Aligning the pick-up
minutes to the upload times is possible but weak (different intervals, drift).

**Status:** Julius cannot decide this alone; a colleague may be able to change the pick-up job. Until
then: best effort, as decided in October, and the plan says plainly that the window exists. Julius
sends any request himself; Claude can draft the text (German, short bullets).

## Julius's answers so far (preferences, not decisions)

- What the pick-up job takes and from where: unknown to Julius; a colleague knows. Open question
  for the colleague (below).
- How strict: rare misses are acceptable, but Julius wants to know when they happen.
- Watchdog: yes, as an ERROR line in the log. No push message for now.

## Recommended scope (draft)

1. **Live round:** cron every minute, daytime only, `timeout -k 10 300` (see above).
2. **Watchdog (new, small, with tests):** a read-only mode, for example
   `blur_box --check-stale`, run from its own cron line every 5 minutes during the day. It lists
   each blur camera over ssh (the listing already carries the upload time of every image), compares
   it with the state files, and logs an ERROR line per camera when a daytime image is older than
   5 minutes and neither blurred, clean nor recorded as a night image: `[SLSV] 2 images unblurred
   for more than 5 minutes: <names>`. It needs no lock, so it also works while a round is stuck, and
   it covers both a stuck job and images that keep failing. It writes nothing to the box. The
   existing per-round "Skipped" line stays as it is.
3. **Pick-up side:** ask the colleague (below); the recommended rule is a minimum age of 4 minutes.
4. **Later:** the Daily gate once the live round is active; a push message (ntfy) only if the log
   line proves too easy to miss.

**Question for the colleague (Julius sends it himself):** what does the job that takes images from
the Storage Box do, from which folders, and how does it decide which files are new? Could it take
only files whose modification time on the box is at least 4 minutes old?

## Before it goes into cron

1. The nightly lines are live on the VPS and the first nights are read (report, flagger, blur
   catch-up log). The live round comes after, so a problem has one cause.
2. Remove `BlurTest` from `privacy.blur_cameras` and from `ignored_cameras` in `config/config.json`
   (it is a test folder; its images are old and its state is complete).
3. Switch the Pi's blur lines off in the same step as the VPS takes over, never both hosts. The
   VPS blur state (`state/privacy/box/*.jsonl`) was copied on 2026-10-27 and lags the Pi's nightly
   blur: either copy the Pi's state over first, or accept one round that judges images the Pi
   already blurred (harmless, extra backups).
4. Accepted gaps from 2026-10-22/23 (unchanged): backups sit in `<camera>/original/` and a
   recursive fetcher could reach them; permanently truncated uploads are never blurred; the
   upload-to-swap window cannot be closed from our side. The website's transfer job should only
   take images at least 3 minutes old; that is the only real guard and it is outside this repo.

## Measuring the delay (after one week)

For each `Replaced <name> with its blurred copy` line in `logs/privacy/<date>.log`, compare its time
with the time inside the image file name. The camera clock may differ by seconds, so read the
spread and the median, not single values. If the median is well above a minute and it matters, look
at option B.

## Out of scope

- The Daily gate (a Daily is only built from confirmed blurred images): Julius builds it once the
  live round is active (docs/plans/2026-10-23-blur-daily-gate.md, part 2).
- A backfill of old images (docs/plans/2026-10-23-blur-catch-up.md).
