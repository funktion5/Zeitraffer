<?php

declare(strict_types=1);

// Included by both index.php and camera.php so a video-creation job's result
// dialog appears no matter which page is open when the job finishes, not only
// the page that started it. $camera is only defined on camera.php.
$jobWatcherCurrentCamera = $camera ?? "";

?>

<dialog id="job-result-dialog" aria-labelledby="job-result-title">
	<h2 id="job-result-title">Video-Auftrag</h2>
	<p id="job-result-message"></p>
	<!-- The result line of every job of a rebuild; hidden for a single manual video. -->
	<ul id="job-result-lines" hidden></ul>

	<form method="dialog" id="job-result-form">
		<button type="submit" id="job-result-dismiss-button">Schließen</button>
		<button type="button" id="job-result-open-button" hidden>Video ansehen</button>
	</form>
</dialog>

<script>
	(function () {
		const PENDING_JOB_KEY = "timelapsePendingJob";
		const CURRENT_CAMERA = <?= json_encode($jobWatcherCurrentCamera, JSON_HEX_TAG | JSON_HEX_AMP) ?>;

		const JOB_LABELS = {
			daily: "Täglich",
			weekly: "Wöchentlich",
			monthly: "Monatlich",
			yearly: "Jährlich",
		};

		const dialog = document.querySelector("#job-result-dialog");
		const title = document.querySelector("#job-result-title");
		const message = document.querySelector("#job-result-message");
		const dismissButton = document.querySelector("#job-result-dismiss-button");
		const openButton = document.querySelector("#job-result-open-button");
		const resultLines = document.querySelector("#job-result-lines");

		let openButtonHandler = null;

		function formatGermanDate(isoDate) {
			const parts = isoDate.split("-");
			return parts.length === 3 ? `${parts[2]}.${parts[1]}.${parts[0]}` : isoDate;
		}

		function buildVideoUrl(pendingJob) {
			// Must match src.video.get_video_path()'s manual-run filename exactly.
			let suffix = "";

			if (pendingJob.bufferMinutes != null) {
				suffix = `_${pendingJob.bufferMinutes}min`;
			} else if (pendingJob.windowTime != null && pendingJob.windowToleranceMinutes != null) {
				// IntervalWindow.label(): "18:30" -> "1830", "sunset" stays as is.
				suffix = `_${pendingJob.windowTime.replace(":", "")}-${pendingJob.windowToleranceMinutes}min`;
			}

			const filename = `${pendingJob.camera}_${pendingJob.targetDate}${suffix}.mp4`;

			return "/camera.php?" + new URLSearchParams({
				camera: pendingJob.camera,
				job: pendingJob.job,
				video: filename,
			}).toString();
		}

		function isRebuild(pendingJob) {
			return pendingJob.kind === "rebuild";
		}

		function isPublish(pendingJob) {
			return pendingJob.kind === "publish";
		}

		function rebuildLabels(pendingJob) {
			return pendingJob.jobs.map((job) => JOB_LABELS[job] ?? job).join(", ");
		}

		// A rebuild or an upload has no single video to open: the dialog lists the result line(s) the
		// worker wrote.
		function showListResult(pendingJob, status, reason, results) {
			const lines = results ?? [];
			const publishing = isPublish(pendingJob);
			const action = publishing ? "Hochladen" : "Neu erstellen";
			const subject = publishing
				? `${pendingJob.camera}: Hochladen`
				: `${pendingJob.camera}: ${rebuildLabels(pendingJob)}`;
			const resultHint = publishing ? " Ergebnis:" : " Ergebnis je Video:";

			if (openButtonHandler !== null) {
				openButton.removeEventListener("click", openButtonHandler);
				openButtonHandler = null;
			}

			if (status === "completed") {
				title.textContent = `${action} abgeschlossen`;
				message.textContent = `${subject} ist fertig.` + (lines.length > 0 ? resultHint : "");
			} else {
				title.textContent = `${action} fehlgeschlagen`;
				// reason: German text from job-status.php for known causes.
				message.textContent = `${subject} konnte nicht abgeschlossen werden. `
					+ (reason ?? "Bitte das Anwendungsprotokoll prüfen.");
			}

			// textContent only: the lines come from the server, never as markup.
			resultLines.replaceChildren(...lines.map((line) => {
				const item = document.createElement("li");
				item.textContent = line;
				return item;
			}));
			resultLines.hidden = lines.length === 0;
			dismissButton.hidden = false;
			dismissButton.textContent = "Schließen";
			openButton.hidden = true;

			if (typeof dialog.showModal === "function") {
				dialog.showModal();
			}
		}

		function showResult(pendingJob, status, reason) {
			const jobLabel = JOB_LABELS[pendingJob.job] ?? pendingJob.job;
			const dateLabel = formatGermanDate(pendingJob.targetDate);
			const onSameCameraPage = CURRENT_CAMERA !== "" && CURRENT_CAMERA === pendingJob.camera;
			resultLines.hidden = true;

			if (openButtonHandler !== null) {
				openButton.removeEventListener("click", openButtonHandler);
				openButtonHandler = null;
			}

			if (status === "completed") {
				title.textContent = "Video erstellt";
				message.textContent = `${jobLabel} für den ${dateLabel} wurde erfolgreich erstellt.`;

				openButtonHandler = () => {
					// Close explicitly before navigating: otherwise the browser's
					// back/forward cache can restore this page later with the
					// dialog still open, since bfcache snapshots live DOM state.
					dialog.close();
					window.location.href = buildVideoUrl(pendingJob);
				};
				openButton.addEventListener("click", openButtonHandler);
				openButton.hidden = false;

				if (onSameCameraPage) {
					// Already on the right camera page: one button does both.
					dismissButton.hidden = true;
					openButton.textContent = "OK";
				} else {
					dismissButton.hidden = false;
					dismissButton.textContent = "Schließen";
					openButton.textContent = "Video ansehen";
				}
			} else {
				title.textContent = "Videoerstellung fehlgeschlagen";
				// reason: German text from job-status.php for known causes (e.g. too few days).
				message.textContent = `${jobLabel} für den ${dateLabel} konnte nicht erstellt werden. `
					+ (reason ?? "Bitte das Anwendungsprotokoll prüfen.");
				dismissButton.hidden = false;
				dismissButton.textContent = "Schließen";
				openButton.hidden = true;
			}

			if (typeof dialog.showModal === "function") {
				dialog.showModal();
			}
		}

		// The job is over: drop the status line and let camera.php's form start the next one.
		function finishLiveStatus() {
			// camera.php's rebuild and upload forms enable their buttons again; they also look at the pending job.
		document.querySelector("#rebuild-form")?.dispatchEvent(new Event("change"));
		document.querySelector("#publish-form")?.dispatchEvent(new Event("change"));

			const liveStatus = document.querySelector("#job-live-status");
			const createButton = document.querySelector('#create-video-form button[type="submit"]');

			if (liveStatus !== null) {
				liveStatus.hidden = true;
			}

			if (createButton !== null) {
				createButton.disabled = false;
			}
		}

		// A page restored from the back/forward cache keeps its old poller; if another page of this
		// tab has finished the job meanwhile, that poller must stop instead of showing it twice.
		function isStillPending(pendingJob) {
			const stored = sessionStorage.getItem(PENDING_JOB_KEY);

			return stored !== null && JSON.parse(stored).jobId === pendingJob.jobId;
		}

		async function pollPendingJob(pendingJob) {
			if (!isStillPending(pendingJob)) {
				finishLiveStatus();
				return;
			}

			try {
				const response = await fetch(
					`/job-status.php?id=${encodeURIComponent(pendingJob.jobId)}`,
					{ cache: "no-store" },
				);

				// The job is gone (status file removed): nothing left to wait for.
				if (response.status === 404) {
					sessionStorage.removeItem(PENDING_JOB_KEY);
					finishLiveStatus();
					return;
				}

				if (!response.ok) {
					throw new Error(`Status request failed with HTTP ${response.status}.`);
				}

				const result = await response.json();

				if (result.status === "running") {
					// On every camera page: it also explains the disabled "Video erstellen" button.
					const liveStatus = document.querySelector("#job-live-status");

					if (liveStatus !== null) {
						const otherCamera = pendingJob.camera !== CURRENT_CAMERA ? ` (${pendingJob.camera})` : "";
						const subject = isRebuild(pendingJob)
							? `Neu erstellen${otherCamera}: ${rebuildLabels(pendingJob)}`
							: isPublish(pendingJob)
								? `Hochladen${otherCamera}`
								: `${JOB_LABELS[pendingJob.job] ?? pendingJob.job}${otherCamera} für den `
									+ formatGermanDate(pendingJob.targetDate);
						const text = `${subject} läuft. Ein neues Video kann erst danach gestartet werden.`;
						liveStatus.hidden = false;

						// Unchanged text is not rewritten, so screen readers announce it once.
						if (liveStatus.textContent !== text) {
							liveStatus.textContent = text;
						}
					}

					window.setTimeout(() => pollPendingJob(pendingJob), 5000);
					return;
				}

				if (result.status === "completed" || result.status === "failed") {
					sessionStorage.removeItem(PENDING_JOB_KEY);
					finishLiveStatus();
					if (isRebuild(pendingJob) || isPublish(pendingJob)) {
						showListResult(pendingJob, result.status, result.reason, result.results);
					} else {
						showResult(pendingJob, result.status, result.reason);
					}
					return;
				}

				throw new Error("The server returned an unknown job status.");
			} catch (error) {
				// A dropped connection or a busy Pi must not end the wait: try again next tick.
				console.error("Video-job polling failed, retrying.", error);
				window.setTimeout(() => pollPendingJob(pendingJob), 5000);
			}
		}

		function resumePendingJob() {
			const stored = sessionStorage.getItem(PENDING_JOB_KEY);

			if (stored === null) {
				return;
			}

			try {
				pollPendingJob(JSON.parse(stored));
			} catch (error) {
				sessionStorage.removeItem(PENDING_JOB_KEY);
				console.error("Could not read the pending video job.", error);
			}
		}

		// A job another colleague (or another tab) started: the camera page says so, so nobody fills
		// in the form only to be refused. The details stay with the tab that started the job, so the
		// text is generic. The create button stays enabled: a start during a run is refused anyway,
		// and the button state belongs to this tab's own job.
		const OTHER_JOB_TEXT = "Gerade läuft ein Auftrag. Ein neues Video kann erst danach gestartet werden.";

		async function pollForOtherJob() {
			try {
				const liveStatus = document.querySelector("#job-live-status");

				// This tab's own job writes its own text there (pollPendingJob).
				if (liveStatus !== null && sessionStorage.getItem(PENDING_JOB_KEY) === null) {
					const response = await fetch("/running-job.php", { cache: "no-store" });

					if (response.ok) {
						const result = await response.json();

						// Look again: this tab may have started a job while the request was out.
						if (sessionStorage.getItem(PENDING_JOB_KEY) === null) {
							liveStatus.hidden = result.running !== true;

							// Unchanged text is not rewritten, so screen readers announce it once.
							if (result.running === true && liveStatus.textContent !== OTHER_JOB_TEXT) {
								liveStatus.textContent = OTHER_JOB_TEXT;
							}
						}
					}
				}
			} catch (error) {
				// A dropped connection must not end the notice: try again next tick.
				console.error("Running-job check failed, retrying.", error);
			}

			window.setTimeout(pollForOtherJob, 5000);
		}

		pollForOtherJob();

		resumePendingJob();

		// Back/forward cache: a restored page did not run the line above again, but a job may
		// have started (or ended) in this tab since it was first loaded.
		window.addEventListener("pageshow", (event) => {
			if (event.persisted) {
				resumePendingJob();
			}
		});
	})();
</script>
