<?php

declare(strict_types=1);

// Included by both index.php and camera.php so a video-creation job's result
// dialog appears no matter which page is open when the job finishes, not only
// the page that started it. $camera is only defined on camera.php.
$jobWatcherCurrentCamera = $camera ?? "";

?>

<dialog id="job-result-dialog">
	<h2 id="job-result-title">Video-Auftrag</h2>
	<p id="job-result-message"></p>

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

		let openButtonHandler = null;

		function formatGermanDate(isoDate) {
			const parts = isoDate.split("-");
			return parts.length === 3 ? `${parts[2]}.${parts[1]}.${parts[0]}` : isoDate;
		}

		function buildVideoUrl(pendingJob) {
			const filename = `${pendingJob.camera}_${pendingJob.targetDate}.mp4`;

			return "/camera.php?" + new URLSearchParams({
				camera: pendingJob.camera,
				job: pendingJob.job,
				video: filename,
			}).toString();
		}

		function showResult(pendingJob, status) {
			const jobLabel = JOB_LABELS[pendingJob.job] ?? pendingJob.job;
			const dateLabel = formatGermanDate(pendingJob.targetDate);
			const onSameCameraPage = CURRENT_CAMERA !== "" && CURRENT_CAMERA === pendingJob.camera;

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
				message.textContent = `${jobLabel} für den ${dateLabel} konnte nicht erstellt werden. Bitte das Anwendungsprotokoll prüfen.`;
				dismissButton.hidden = false;
				dismissButton.textContent = "Schließen";
				openButton.hidden = true;
			}

			if (typeof dialog.showModal === "function") {
				dialog.showModal();
			}
		}

		async function pollPendingJob(pendingJob) {
			try {
				const response = await fetch(
					`/job-status.php?id=${encodeURIComponent(pendingJob.jobId)}`,
					{ cache: "no-store" },
				);

				if (!response.ok) {
					throw new Error(`Status request failed with HTTP ${response.status}.`);
				}

				const result = await response.json();

				if (result.status === "running") {
					if (CURRENT_CAMERA !== "" && CURRENT_CAMERA === pendingJob.camera) {
						const liveStatus = document.querySelector("#job-live-status");

						if (liveStatus !== null) {
							const jobLabel = JOB_LABELS[pendingJob.job] ?? pendingJob.job;
							liveStatus.hidden = false;
							liveStatus.textContent = `${jobLabel} für den ${formatGermanDate(pendingJob.targetDate)} läuft.`;
						}
					}

					window.setTimeout(() => pollPendingJob(pendingJob), 5000);
					return;
				}

				if (result.status === "completed" || result.status === "failed") {
					sessionStorage.removeItem(PENDING_JOB_KEY);
					showResult(pendingJob, result.status);
					return;
				}

				throw new Error("The server returned an unknown job status.");
			} catch (error) {
				console.error("Video-job polling stopped.", error);
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

		resumePendingJob();
	})();
</script>
