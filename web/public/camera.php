<?php

declare(strict_types=1);
session_start();

require_once __DIR__ . "/../src/video-library.php";
require_once __DIR__ . "/../src/job-runner.php";
require_once __DIR__ . "/../src/video-delete.php";

$camera = $_GET["camera"] ?? "";
$availableCameras = findAvailableCameras();

$storage = getStorageUsage();

if (!in_array($camera, $availableCameras, true)) {
  http_response_code(404);
  $camera = "";
}

$manualVideos = $camera === "" ? [] : findManualVideos($camera);

$selectedJob = $_GET["job"] ?? "";
$selectedFilename = $_GET["video"] ?? "";
$selectedVideo = null;
$videoWasDeleted = ($_GET["deleted"] ?? null) === "1";

if (isset($manualVideos[$selectedJob])) {
  foreach ($manualVideos[$selectedJob] as $video) {
    if ($video["filename"] === $selectedFilename) {
      $selectedVideo = $video;
			break;
		}
	}
}

if (!isset($_SESSION["csrf_token"])) {
  $_SESSION["csrf_token"] = bin2hex(random_bytes(32));
}

$csrfToken = $_SESSION["csrf_token"];

$allowedJobs = [
  "daily",
  "weekly",
  "monthly",
  "yearly",
];

$allowedDaylightBuffers = [
  "30",
  "60",
  "90",
];

$formMessage = null;
$formIsValid = false;
$activeJobId = null;
$activeJobType = null;
$activeTargetDate = null;
$activeDaylightBufferMinutes = null;

if ($_SERVER["REQUEST_METHOD"] === "POST") {
	$submittedAction = $_POST["action"] ?? null;
	$submittedToken = $_POST["csrf_token"] ?? null;
	$submittedCamera = $_POST["camera"] ?? null;
	$submittedJob = $_POST["job"] ?? null;

	// Validate CSRF token first.
	if (
		!is_string($submittedToken)
		|| !hash_equals($csrfToken, $submittedToken)
	) {
		$formMessage = "Die Anfrage ist ungültig (Sicherheitstoken).";

	// Validate that the submitted camera is the current available camera.
	} elseif (
		!is_string($submittedCamera)
		|| $submittedCamera !== $camera
		|| !in_array($submittedCamera, $availableCameras, true)
	) {
		$formMessage = "Die ausgewählte Kamera ist ungültig.";

	// ----------------------------------------------------------------------
	// Delete video
	// ----------------------------------------------------------------------
	} elseif ($submittedAction === "delete-video") {
		$submittedFilename = $_POST["video"] ?? null;

		if (
			!is_string($submittedJob)
			|| !in_array($submittedJob, $allowedJobs, true)
		) {
			$formMessage = "Der ausgewählte Videotyp ist ungültig.";

		} elseif (!is_string($submittedFilename)) {
			$formMessage = "Das ausgewählte Video ist ungültig.";

		} else {
			$videoExists = false;

			foreach ($manualVideos[$submittedJob] ?? [] as $video) {
				if ($video["filename"] === $submittedFilename) {
					$videoExists = true;
					break;
				}
			}

			if (!$videoExists) {
				$formMessage = "Das ausgewählte Video wurde nicht gefunden.";

			} else {
				$deleteResult = deleteManualVideo(
					$submittedCamera,
					$submittedJob,
					$submittedFilename,
				);

				$formMessage = $deleteResult["message"];

				if ($deleteResult["deleted"]) {
					header(
						"Location: /camera.php?camera="
						. rawurlencode($camera)
						. "&deleted=1"
					);

					exit;
				}
			}
		}

	// ----------------------------------------------------------------------
	// Create historical video
	// ----------------------------------------------------------------------
	} elseif ($submittedAction === "create-video") {
		$submittedDate = $_POST["target_date"] ?? null;
		$submittedBuffer = $_POST["daylight_buffer_minutes"] ?? null;

		if (
			!is_string($submittedJob)
			|| !in_array($submittedJob, $allowedJobs, true)
		) {
			$formMessage = "Der ausgewählte Auftragstyp ist ungültig.";

		} elseif (
			!is_string($submittedDate)
			|| !isValidIsoDate($submittedDate)
		) {
			$formMessage = "Das Zieldatum ist ungültig.";

		} elseif (
			!is_string($submittedBuffer)
			|| !in_array($submittedBuffer, $allowedDaylightBuffers, true)
		) {
			$formMessage = "Der ausgewählte Zeitpuffer ist ungültig.";

		} else {
			$formIsValid = true;

			$jobResult = startVideoJob(
				$submittedJob,
				$submittedDate,
				$submittedCamera,
				(int) $submittedBuffer,
			);

			$formMessage = $jobResult["message"];
			$activeJobId = $jobResult["jobId"];

			if ($jobResult["started"]) {
				$activeJobType = $submittedJob;
				$activeTargetDate = $submittedDate;
				$activeDaylightBufferMinutes = (int) $submittedBuffer;
			}
		}

	} else {
		$formMessage = "Unbekannte Anfrage.";
	}
}

?>

<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="stylesheet" href="/style.css">
  <title><?= $camera !== "" ? htmlspecialchars($camera, ENT_QUOTES, "UTF-8") . " – Zeitraffer" : "Kamera nicht gefunden – Zeitraffer" ?></title>
</head>
<body>
  <header>
    <?php require __DIR__ . "/../src/components/header.php"; ?>
  </header>
  <main>
    <?php if ($camera === ""): ?>
      <h1>Kamera nicht gefunden</h1>
    <?php else: ?>
	      <h1><?= htmlspecialchars($camera, ENT_QUOTES, "UTF-8")?></h1>
	        <?php if ($videoWasDeleted): ?>
	          <p class="delete-success-message">Video erfolgreich gelöscht.</p>
	        <?php endif; ?>
	        <div>
	          <section>
	            <h2>Videoplayer</h2>

	            <?php if ($selectedVideo === null): ?>
	              <p>Bitte ein Video aus der Liste auswählen.</p>
	            <?php else: ?>
	              <video controls preload="metadata" width="720">
	                <source
	                  src="<?= htmlspecialchars($selectedVideo["url"], ENT_QUOTES, "UTF-8") ?>"
	                  type="video/mp4"
	                >
	                Der Browser unterstützt keine MP4-Wiedergabe.
	              </video>
							<div class="video-actions">
								<a
									href="<?= htmlspecialchars($selectedVideo["url"], ENT_QUOTES, "UTF-8") ?>"
									download
									class="download-video-button"
									title="Video herunterladen"
									aria-label="<?= htmlspecialchars(
										$selectedVideo["filename"],
										ENT_QUOTES,
										"UTF-8",
									) ?> herunterladen"
								>
									<svg viewBox="0 0 24 24" aria-hidden="true">
										<path d="M12 16l-5-5h3V4h4v7h3l-5 5zm-7 2h14v2H5v-2z" />
									</svg>
									<span>Herunterladen</span>
								</a>

							<form
								method="post"
								action="/camera.php?camera=<?= rawurlencode($camera) ?>"
								class="video-delete-form"
								data-delete-video
								data-video-name="<?= htmlspecialchars(
									$selectedVideo["filename"],
									ENT_QUOTES,
									"UTF-8",
								) ?>"
							>
								<input type="hidden" name="action" value="delete-video">

								<input
									type="hidden"
									name="csrf_token"
									value="<?= htmlspecialchars($csrfToken, ENT_QUOTES, "UTF-8") ?>"
								>

								<input
									type="hidden"
									name="camera"
									value="<?= htmlspecialchars($camera, ENT_QUOTES, "UTF-8") ?>"
								>

								<input
									type="hidden"
									name="job"
									value="<?= htmlspecialchars($selectedJob, ENT_QUOTES, "UTF-8") ?>"
								>

								<input
									type="hidden"
									name="video"
									value="<?= htmlspecialchars(
										$selectedVideo["filename"],
										ENT_QUOTES,
										"UTF-8",
									) ?>"
								>

								<button
									type="submit"
									class="delete-video-button"
									title="Video löschen"
									aria-label="<?= htmlspecialchars(
										$selectedVideo["filename"],
										ENT_QUOTES,
										"UTF-8",
									) ?> löschen"
								>
									<svg viewBox="0 0 24 24" aria-hidden="true">
										<path
											d="M9 3h6l1 2h4v2H4V5h4l1-2Zm-2 6h10l-1 12H8L7 9Zm3 2v7h2v-7h-2Zm4 0v7h2v-7h-2Z"
										/>
									</svg>
									<span>Löschen</span>
								</button>
							</form>
							</div>
	            <?php endif; ?>
	          </section>

	          <section>
            <h2>Manuelle Videos</h2>
            <?php if ($manualVideos === []): ?>
              <p>Keine manuellen Videos gefunden.</p>
            <?php else: ?>
              <?php foreach ($manualVideos as $job => $videos): ?>
                <details<?= $job === $selectedJob ? " open" : "" ?>>
                  <summary>
                    <?= htmlspecialchars(translateJobLabel($job), ENT_QUOTES, "UTF-8") ?>
                  </summary>
                    <ul>
	                      <?php foreach ($videos as $video): ?>
													<?php
														$videoDisplayLabel = $video["date"] !== null ? formatGermanDate($video["date"]) : $video["filename"];
														if ($video["bufferMinutes"] !== null) {
															$videoDisplayLabel .= " ({$video["bufferMinutes"]} Min.)";
														}
													?>
													<li class="video-library-item">

														<a href="/camera.php?<?= htmlspecialchars(
															http_build_query([
																"camera" => $camera,
																"job" => $job,
																"video" => $video["filename"],
															]),
															ENT_QUOTES,
															"UTF-8",
														) ?>">
															<?= htmlspecialchars(
																$videoDisplayLabel,
																ENT_QUOTES,
																"UTF-8",
															) ?>
														</a>

														<form
															method="post"
															action="/camera.php?camera=<?= rawurlencode($camera) ?>"
															class="video-library-delete-form"
															data-delete-video
															data-video-name="<?= htmlspecialchars(
																$video["filename"],
																ENT_QUOTES,
																"UTF-8",
															) ?>"
														>
															<input
																type="hidden"
																name="action"
																value="delete-video"
															>

															<input
																type="hidden"
																name="csrf_token"
																value="<?= htmlspecialchars(
																	$csrfToken,
																	ENT_QUOTES,
																	"UTF-8",
																) ?>"
															>

															<input
																type="hidden"
																name="camera"
																value="<?= htmlspecialchars(
																	$camera,
																	ENT_QUOTES,
																	"UTF-8",
																) ?>"
															>

															<input
																type="hidden"
																name="job"
																value="<?= htmlspecialchars(
																	$job,
																	ENT_QUOTES,
																	"UTF-8",
																) ?>"
															>

															<input
																type="hidden"
																name="video"
																value="<?= htmlspecialchars(
																	$video["filename"],
																	ENT_QUOTES,
																	"UTF-8",
																) ?>"
															>

															<button
																type="submit"
																class="video-library-delete"
																title="Video löschen"
																aria-label="<?= htmlspecialchars(
																	$video["filename"],
																	ENT_QUOTES,
																	"UTF-8",
																) ?> löschen"
															>
																<svg
																	viewBox="0 0 24 24"
																	aria-hidden="true"
																>
																	<path
																		d="M9 3h6l1 2h4v2H4V5h4l1-2Zm-2 6h10l-1 12H8L7 9Zm3 2v7h2v-7h-2Zm4 0v7h2v-7h-2Z"
																	/>
																</svg>
															</button>
														</form>

													</li>
												<?php endforeach; ?>
                    </ul>
                </details>
              <?php endforeach; ?>
            <?php endif; ?>
          </section>
	          <section>
	            <h2>Historisches Video erstellen</h2>

	            <div class="job-instructions">
	              <p>Das Zieldatum ist immer der <strong>letzte Tag</strong> des Zeitraums, nicht der erste.</p>
	              <ul>
	                <li><strong>Täglich:</strong> zeigt genau den gewählten Tag.</li>
	                <li><strong>Wöchentlich:</strong> die 7 Tage bis einschließlich des gewählten Datums.</li>
	                <li><strong>Monatlich:</strong> die 30 Tage bis einschließlich des gewählten Datums (kein Kalendermonat).</li>
	                <li><strong>Jährlich:</strong> die 365 Tage bis einschließlich des gewählten Datums. Beispiel: Zieldatum 31.12.2025 ergibt das Jahr 2025.</li>
	              </ul>
	              <p>Fehlt an einem einzigen Tag im Zeitraum ein brauchbares Bild, wird für Monatlich/Jährlich kein Video erstellt.</p>
	            </div>

	              <?php if ($formMessage !== null): ?>
                <p>
                  <?= htmlspecialchars($formMessage, ENT_QUOTES, "UTF-8") ?>
                </p>
	                <?php endif; ?>
	              <p id="job-live-status" role="status" aria-live="polite" hidden></p>
	            <form method="post"
                    action="/camera.php?camera=<?= rawurlencode($camera) ?>">
							<input
								type="hidden"
								name="action"
								value="create-video"
							>
	              <input
	                type="hidden"
	                name="camera"
	                value="<?= htmlspecialchars($camera, ENT_QUOTES, "UTF-8") ?>"
	              >
                 <input
	                type="hidden"
	                name="csrf_token"
	                value="<?= htmlspecialchars($csrfToken, ENT_QUOTES, "UTF-8") ?>"
	              >
	              <fieldset>
	                <legend>Auftragstyp</legend>

	                <label>
	                  <input type="radio" name="job" value="daily" required>
	                  Täglich
	                </label>

	                <label>
	                  <input type="radio" name="job" value="weekly">
	                  Wöchentlich
	                </label>

	                <label>
	                  <input type="radio" name="job" value="monthly">
	                  Monatlich
	                </label>

	                <label>
	                  <input type="radio" name="job" value="yearly">
	                  Jährlich
	                </label>
	              </fieldset>

	              <fieldset>
	                <legend>Zeitpuffer</legend>

	                <label>
	                  <input type="radio" name="daylight_buffer_minutes" value="30">
	                  30 Min.
	                </label>

	                <label>
	                  <input type="radio" name="daylight_buffer_minutes" value="60">
	                  60 Min.
	                </label>

	                <label>
	                  <input type="radio" name="daylight_buffer_minutes" value="90" checked>
	                  90 Min.
	                </label>
	              </fieldset>

	              <div>
	                <label for="target-date">Zieldatum</label>
	                <input
	                  id="target-date"
	                  type="date"
	                  name="target_date"
	                  required
	                >
	              </div>

	              <button type="submit">
	                Video erstellen
	              </button>

	            </form>
	          </section>
	        </div>
    <?php endif; ?>
	  </main>

	  <dialog id="confirm-delete-dialog">
	    <h2 id="confirm-delete-title">Video löschen</h2>
	    <p id="confirm-delete-message"></p>

	    <form method="dialog">
	      <button type="submit">Abbrechen</button>
	      <button type="button" id="confirm-delete-button">Löschen</button>
	    </form>
	  </dialog>

	  <script>
	    // A job was just started on this exact page load: hand it to the shared
	    // job-watcher (job-watcher.php, required right below) before it runs,
	    // so it polls this job to completion from wherever the user happens to
	    // be, even after navigating away, without needing a page reload here.
	    const activeJobId = <?= json_encode($activeJobId, JSON_HEX_TAG | JSON_HEX_AMP) ?>;

	    if (activeJobId !== null) {
	      sessionStorage.setItem(
	        "timelapsePendingJob",
	        JSON.stringify({
	          jobId: activeJobId,
	          job: <?= json_encode($activeJobType, JSON_HEX_TAG | JSON_HEX_AMP) ?>,
	          targetDate: <?= json_encode($activeTargetDate, JSON_HEX_TAG | JSON_HEX_AMP) ?>,
	          camera: <?= json_encode($camera, JSON_HEX_TAG | JSON_HEX_AMP) ?>,
	          bufferMinutes: <?= json_encode($activeDaylightBufferMinutes, JSON_HEX_TAG | JSON_HEX_AMP) ?>,
	        }),
	      );
	    }
	  </script>

	  <?php require __DIR__ . "/../src/components/job-watcher.php"; ?>

	  <script>
	    const videoWasDeleted = <?= json_encode($videoWasDeleted, JSON_HEX_TAG | JSON_HEX_AMP) ?>;

	    // Drop ?deleted=1 from the URL so a later refresh doesn't re-show the message.
	    if (videoWasDeleted) {
	      const url = new URL(window.location.href);
	      url.searchParams.delete("deleted");
	      window.history.replaceState(null, "", url);
	    }

	    const deleteDialog = document.querySelector("#confirm-delete-dialog");
	    const deleteDialogMessage = document.querySelector("#confirm-delete-message");
	    const deleteDialogConfirmButton = document.querySelector("#confirm-delete-button");
	    let pendingDeleteForm = null;

	    function buildDeleteConfirmMessage(videoName) {
	      return `„${videoName}“ wirklich löschen? Dies kann nicht rückgängig gemacht werden.`;
	    }

	    // Require an explicit confirm click before any delete form is submitted.
	    // Falls back to window.confirm() where <dialog>.showModal is unavailable,
	    // so the delete action never silently does nothing.
	    document.querySelectorAll("form[data-delete-video]").forEach((form) => {
	      form.addEventListener("submit", (event) => {
	        event.preventDefault();

	        if (typeof deleteDialog.showModal !== "function") {
	          if (window.confirm(buildDeleteConfirmMessage(form.dataset.videoName))) {
	            form.submit();
	          }

	          return;
	        }

	        pendingDeleteForm = form;
	        deleteDialogMessage.textContent = buildDeleteConfirmMessage(form.dataset.videoName);
	        deleteDialog.showModal();
	      });
	    });

	    deleteDialogConfirmButton.addEventListener("click", () => {
	      const form = pendingDeleteForm;
	      pendingDeleteForm = null;

	      if (form !== null) {
	        form.submit();
	      }
	    });
	  </script>
	</body>
</html>
