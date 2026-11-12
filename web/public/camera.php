<?php

declare(strict_types=1);
session_start();

require_once __DIR__ . "/../src/video-library.php";
require_once __DIR__ . "/../src/job-runner.php";
require_once __DIR__ . "/../src/rebuild-runner.php";
require_once __DIR__ . "/../src/publish-runner.php";
require_once __DIR__ . "/../src/video-delete.php";
require_once __DIR__ . "/../src/json-response.php";

$camera = $_GET["camera"] ?? "";
$availableCameras = findAvailableCameras();

$storage = getStorageUsage();

if (!in_array($camera, $availableCameras, true)) {
  http_response_code(404);
  $camera = "";
}

// A manual video of these cameras (any job type) blurs its frames first and takes longer.
$cameraIsBlurred = $camera !== "" && in_array($camera, getBlurCameras(), true);

// The daylight buffer of a manual Daily/Weekly is the saved setting: the form names it, never asks.
$savedDaylightBuffer = getManualDaylightBuffer();

$manualVideos = $camera === "" ? [] : findVideos($camera, "manual-runs");
$automaticVideos = $camera === "" ? [] : findVideos($camera, "");
// What an upload would send (the upload section lists it and is absent when it is empty).
$publishVideos = $camera === "" ? [] : newestAutomaticVideos($camera);

// Strings only: an array here (?job[]=x) would make the lookups below throw.
$selectedJob = is_string($_GET["job"] ?? null) ? $_GET["job"] : "";
$selectedFilename = is_string($_GET["video"] ?? null) ? $_GET["video"] : "";
// Automatic videos are read-only; the same filename can exist in both lists.
$selectedSource = ($_GET["source"] ?? null) === "auto" ? "auto" : "manual";
$selectedVideo = null;
$videoWasDeleted = ($_GET["deleted"] ?? null) === "1";
$selectedList = $selectedSource === "auto" ? $automaticVideos : $manualVideos;

foreach ($selectedList[$selectedJob] ?? [] as $video) {
	if ($video["filename"] === $selectedFilename) {
		$selectedVideo = $video;
		break;
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

// Single source of truth for "which job types use a daylight buffer at all" —
// shared with the client-side visibility toggle via the JSON payload below,
// so the two never drift out of sync.
$daylightBufferJobs = ["daily", "weekly"];

// Monthly/Yearly interval window choices. "default" sends nothing, so the
// CLI keeps using config.json's interval_window (12:00 +-90 min).
$intervalWindowJobs = ["monthly", "yearly"];

$allowedIntervalWindows = [
  "default",
  "sunset",
];

$allowedWindowTolerances = [
  "30",
  "60",
  "90",
];

$formMessage = null;
// Set from the POST below; the page shows a message in the form section the request came from.
$submittedAction = null;
$videoDeleted = false;

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
				$videoDeleted = $deleteResult["deleted"];
			}
		}

	// ----------------------------------------------------------------------
	// Create historical video
	// ----------------------------------------------------------------------
	} elseif ($submittedAction === "create-video") {
		$submittedDate = $_POST["target_date"] ?? null;
		$submittedWindow = $_POST["interval_window"] ?? null;
		$submittedWindowTolerance = $_POST["window_tolerance_minutes"] ?? null;
		$jobUsesIntervalWindow = in_array($submittedJob, $intervalWindowJobs, true);
		$windowIsSunset = $jobUsesIntervalWindow && $submittedWindow === "sunset";
		// Only Daily/Weekly's image selection consults the daylight buffer, and it is the saved
		// setting: a buffer sent by a client (an old tab) is never read.
		$jobUsesDaylightBuffer = in_array($submittedJob, $daylightBufferJobs, true);

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

		} elseif ($jobUsesDaylightBuffer && $savedDaylightBuffer === null) {
			$formMessage = "Die Einstellungen konnten nicht gelesen werden.";

		} elseif (
			$jobUsesIntervalWindow
			&& (
				!is_string($submittedWindow)
				|| !in_array($submittedWindow, $allowedIntervalWindows, true)
			)
		) {
			$formMessage = "Das ausgewählte Zeitfenster ist ungültig.";

		} elseif (
			$windowIsSunset
			&& (
				!is_string($submittedWindowTolerance)
				|| !in_array($submittedWindowTolerance, $allowedWindowTolerances, true)
			)
		) {
			$formMessage = "Die ausgewählte Fensterbreite ist ungültig.";

		} else {
			// For the job watcher, which names the video it waits for after this buffer.
			$daylightBufferMinutes = $jobUsesDaylightBuffer ? $savedDaylightBuffer : null;
			// Only the sunset choice overrides the window; Daily/Weekly never get one.
			$windowTime = $windowIsSunset ? "sunset" : null;
			$windowToleranceMinutes = $windowIsSunset ? (int) $submittedWindowTolerance : null;

			$jobResult = startVideoJob(
				$submittedJob,
				$submittedDate,
				$submittedCamera,
				$windowTime,
				$windowToleranceMinutes,
			);

			$formMessage = $jobResult["message"];

			// Post/Redirect/Get: a reload or a second click cannot start the job again. The
			// next page load hands it to the job watcher (see startedJob below).
			if ($jobResult["started"]) {
				$_SESSION["started_job"] = [
					"jobId" => $jobResult["jobId"],
					"job" => $submittedJob,
					"targetDate" => $submittedDate,
					"camera" => $submittedCamera,
					"bufferMinutes" => $daylightBufferMinutes,
					"windowTime" => $windowTime,
					"windowToleranceMinutes" => $windowToleranceMinutes,
				];
				header("Location: /camera.php?camera=" . rawurlencode($camera));

				exit;
			}
		}

	// ----------------------------------------------------------------------
	// Rebuild the automatic videos (what the night run does for this camera)
	// ----------------------------------------------------------------------
	} elseif ($submittedAction === "rebuild-jobs") {
		$submittedRebuildJobs = $_POST["rebuild_jobs"] ?? [];

		if (!is_array($submittedRebuildJobs)) {
			$formMessage = "Der ausgewählte Videotyp ist ungültig.";

		} elseif ($submittedRebuildJobs === []) {
			$formMessage = "Bitte mindestens ein Video zum Neuerstellen auswählen.";

		// A crafted request: any value that is not exactly one of the four job names refuses the
		// whole request. (in_array is strict, so a nested array never causes a warning.)
		} elseif (array_filter(
			$submittedRebuildJobs,
			static fn ($job): bool => !is_string($job) || !in_array($job, $allowedJobs, true),
		) !== []) {
			$formMessage = "Der ausgewählte Videotyp ist ungültig.";

		} else {
			// The fixed order of $allowedJobs, each job once, whatever the browser sent.
			$rebuildJobs = array_values(array_filter(
				$allowedJobs,
				static fn (string $job): bool => in_array($job, $submittedRebuildJobs, true),
			));

			$jobResult = startRebuildJob($submittedCamera, $rebuildJobs);

			$formMessage = $jobResult["message"];

			// Post/Redirect/Get, as for the manual video above.
			if ($jobResult["started"]) {
				$_SESSION["started_job"] = [
					"kind" => "rebuild",
					"jobId" => $jobResult["jobId"],
					"jobs" => $rebuildJobs,
					"camera" => $submittedCamera,
				];
				header("Location: /camera.php?camera=" . rawurlencode($camera));

				exit;
			}
		}

	// ----------------------------------------------------------------------
	// Upload the newest automatic videos of this camera to the website
	// ----------------------------------------------------------------------
	} elseif ($submittedAction === "publish-camera") {
		// Only the exact string "yes" confirms: a bare checkbox sends "on", and a crafted request
		// can send anything, also an array. The disabled button in the browser is no check.
		if (($_POST["confirm"] ?? null) !== "yes") {
			$formMessage = "Bitte bestätigen, dass die Videos übertragen werden sollen.";

		} else {
			$jobResult = startPublishJob($submittedCamera);

			$formMessage = $jobResult["message"];

			// Post/Redirect/Get, as for the other jobs above.
			if ($jobResult["started"]) {
				$_SESSION["started_job"] = [
					"kind" => "publish",
					"jobId" => $jobResult["jobId"],
					"camera" => $submittedCamera,
				];
				header("Location: /camera.php?camera=" . rawurlencode($camera));

				exit;
			}
		}

	} else {
		$formMessage = "Unbekannte Anfrage.";
	}

	// The background delete (confirm-delete.php) only needs the outcome.
	if (($_POST["response"] ?? null) === "json") {
		respondWithJson(200, ["deleted" => $videoDeleted, "message" => $formMessage]);
	}

	// Without JavaScript: back to the page with the same list open.
	if ($videoDeleted) {
		header(
			"Location: /camera.php?"
			. http_build_query(["camera" => $camera, "job" => $submittedJob, "deleted" => "1"])
		);

		exit;
	}
}

// Set once by the redirect after a job start; read and dropped on the next page load.
$startedJob = $_SESSION["started_job"] ?? null;
unset($_SESSION["started_job"]);

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
	        <p class="delete-success-message" id="delete-success-message"<?= $videoWasDeleted ? "" : " hidden" ?>>Video erfolgreich gelöscht.</p>
	        <div class="camera-layout">
	          <section class="video-player">
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

							<?php if ($selectedSource === "manual"): ?>
							<form
								method="post"
								action="/camera.php?camera=<?= rawurlencode($camera) ?>"
								class="video-delete-form"
								data-delete-confirm
								data-delete-name="<?= htmlspecialchars(
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
							<?php endif; ?>
							</div>
	            <?php endif; ?>
	          </section>

		<section class="video-library">
			<?php
			$librarySources = [
				"auto" => ["Automatische Videos", $automaticVideos, "Keine automatischen Videos gefunden."],
				"manual" => ["Manuelle Videos", $manualVideos, "Keine manuellen Videos gefunden."],
			];
			?>
			<?php foreach ($librarySources as $source => [$heading, $videoGroups, $emptyText]): ?>
				<div
					class="video-library-source"
					data-video-source="<?= htmlspecialchars($source, ENT_QUOTES, "UTF-8") ?>"
					data-empty-text="<?= htmlspecialchars($emptyText, ENT_QUOTES, "UTF-8") ?>"
				>
					<h2><?= htmlspecialchars($heading, ENT_QUOTES, "UTF-8") ?></h2>

					<?php if ($videoGroups === []): ?>
						<p><?= htmlspecialchars($emptyText, ENT_QUOTES, "UTF-8") ?></p>
					<?php endif; ?>

					<?php foreach ($videoGroups as $job => $videos): ?>
						<details<?= $source === $selectedSource && $job === $selectedJob ? " open" : "" ?>>
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
									if ($video["window"] !== null) {
										$videoDisplayLabel .= " ({$video["window"]})";
									}
									$videoQuery = ["camera" => $camera, "job" => $job, "video" => $video["filename"]];
									if ($source === "auto") {
										$videoQuery["source"] = "auto";
									}
									?>
									<li class="video-library-item">
										<a
											href="/camera.php?<?= htmlspecialchars(http_build_query($videoQuery), ENT_QUOTES, "UTF-8") ?>"
											<?= $selectedVideo !== null && $source === $selectedSource && $job === $selectedJob && $video["filename"] === $selectedVideo["filename"] ? 'aria-current="true"' : "" ?>
										>
											<?= htmlspecialchars($videoDisplayLabel, ENT_QUOTES, "UTF-8") ?>
										</a>

										<?php if ($source === "manual"): ?>
											<form
												method="post"
												action="/camera.php?camera=<?= rawurlencode($camera) ?>"
												class="video-library-delete-form"
												data-delete-confirm
												data-delete-name="<?= htmlspecialchars($video["filename"], ENT_QUOTES, "UTF-8") ?>"
											>
												<input type="hidden" name="action" value="delete-video">
												<input type="hidden" name="csrf_token" value="<?= htmlspecialchars($csrfToken, ENT_QUOTES, "UTF-8") ?>">
												<input type="hidden" name="camera" value="<?= htmlspecialchars($camera, ENT_QUOTES, "UTF-8") ?>">
												<input type="hidden" name="job" value="<?= htmlspecialchars($job, ENT_QUOTES, "UTF-8") ?>">
												<input type="hidden" name="video" value="<?= htmlspecialchars($video["filename"], ENT_QUOTES, "UTF-8") ?>">

												<button
													type="submit"
													class="video-library-delete"
													aria-label="<?= htmlspecialchars($video["filename"], ENT_QUOTES, "UTF-8") ?> löschen"
												>
													<svg viewBox="0 0 24 24" aria-hidden="true">
														<path d="M9 3h6l1 2h4v2H4V5h4l1-2Zm-2 6h10l-1 12H8L7 9Zm3 2v7h2v-7h-2Zm4 0v7h2v-7h-2Z" />
													</svg>
												</button>
											</form>
										<?php endif; ?>
									</li>
								<?php endforeach; ?>
							</ul>
						</details>
					<?php endforeach; ?>
				</div>
			<?php endforeach; ?>
		</section>
	          <?php // Closed by default; open again after a refused request so its message is seen. ?>
		<details class="video-tools"<?= in_array($submittedAction, ["rebuild-jobs", "publish-camera"], true) ? " open" : "" ?>>
			<summary>Automatische Videos neu erstellen und hochladen</summary>

		<section class="video-rebuild">
			<h2>Neu erstellen wie der Nachtlauf</h2>

			<div class="job-instructions">
				<p>Baut die automatischen Videos dieser Kamera neu, mit denselben Einstellungen wie der Nachtlauf. Ein neu erstelltes Video ersetzt das vorhandene. Ein Zieldatum gibt es hier nicht.</p>
				<p><strong>Wöchentlich</strong> baut auf den vorhandenen Täglich-Videos auf. Fehlt ein Tagesvideo, Täglich mit ankreuzen.</p>
				<p>Das kann lange dauern. Solange es läuft, kann kein anderer Auftrag starten und kein Nachtlauf beginnen.</p>
			</div>

			<?php if ($formMessage !== null && $submittedAction === "rebuild-jobs"): ?>
				<p class="form-message"><?= htmlspecialchars($formMessage, ENT_QUOTES, "UTF-8") ?></p>
			<?php endif; ?>

			<form method="post" id="rebuild-form" action="/camera.php?camera=<?= rawurlencode($camera) ?>">
				<input type="hidden" name="action" value="rebuild-jobs">
				<input type="hidden" name="camera" value="<?= htmlspecialchars($camera, ENT_QUOTES, "UTF-8") ?>">
				<input type="hidden" name="csrf_token" value="<?= htmlspecialchars($csrfToken, ENT_QUOTES, "UTF-8") ?>">

				<fieldset>
					<legend>Welche Videos neu erstellen?</legend>

					<?php foreach ($allowedJobs as $rebuildJob): ?>
						<label>
							<input type="checkbox" name="rebuild_jobs[]" value="<?= htmlspecialchars($rebuildJob, ENT_QUOTES, "UTF-8") ?>">
							<?= htmlspecialchars(translateJobLabel($rebuildJob), ENT_QUOTES, "UTF-8") ?>
						</label>
					<?php endforeach; ?>
				</fieldset>

				<button type="submit" disabled>Neu erstellen</button>
			</form>
		</section>

		          <?php if ($publishVideos !== []): ?>
		<section class="video-publish">
			<h2>Auf die Website übertragen</h2>

			<div class="job-instructions">
				<p>Überträgt die neuesten automatischen Videos dieser Kamera auf die Website, so wie es der Nachtlauf jede Nacht tut. Diese Videos werden gesendet:</p>
				<ul>
					<?php foreach ($publishVideos as $publishJob => $publishFilename): ?>
						<li><strong><?= htmlspecialchars(translateJobLabel($publishJob), ENT_QUOTES, "UTF-8") ?>:</strong> <code><?= htmlspecialchars($publishFilename, ENT_QUOTES, "UTF-8") ?></code></li>
					<?php endforeach; ?>
				</ul>
				<p>Videos, die schon mit gleicher Größe auf der Website liegen, werden übersprungen. Ältere Videos auf der Website werden dabei gelöscht: Von jedem Zeitraum bleiben dort die zwei neuesten.</p>
			</div>

			<?php if ($formMessage !== null && $submittedAction === "publish-camera"): ?>
				<p class="form-message"><?= htmlspecialchars($formMessage, ENT_QUOTES, "UTF-8") ?></p>
			<?php endif; ?>

			<form method="post" id="publish-form" action="/camera.php?camera=<?= rawurlencode($camera) ?>">
				<input type="hidden" name="action" value="publish-camera">
				<input type="hidden" name="camera" value="<?= htmlspecialchars($camera, ENT_QUOTES, "UTF-8") ?>">
				<input type="hidden" name="csrf_token" value="<?= htmlspecialchars($csrfToken, ENT_QUOTES, "UTF-8") ?>">

				<label>
					<input type="checkbox" name="confirm" value="yes">
					Ja, diese Videos jetzt auf die Website übertragen
				</label>

				<button type="submit" disabled>Auf die Website übertragen</button>
			</form>
		</section>
		<?php endif; ?>

		          </details>

		<section class="video-create">
	            <h2>Historisches Video erstellen</h2>

	            <div class="job-instructions">
	              <p>Das Zieldatum ist immer der <strong>letzte Tag</strong> des Zeitraums, nicht der erste.</p>
	              <ul>
	                <li><strong>Täglich:</strong> zeigt genau den gewählten Tag.</li>
	                <li><strong>Wöchentlich:</strong> die 7 Tage bis einschließlich des gewählten Datums.</li>
	                <li><strong>Monatlich:</strong> die 30 Tage bis einschließlich des gewählten Datums (kein Kalendermonat).</li>
	                <li><strong>Jährlich:</strong> die 365 Tage bis einschließlich des gewählten Datums. Beispiel: Zieldatum 31.12.2025 ergibt das Jahr 2025.</li>
	              </ul>
	              <p>Monatlich braucht mindestens 25 der 30 Tage, Jährlich mindestens 300 Tage mit Bildern im gewählten Zeitfenster. Fehlende Tage werden im Video übersprungen; sind es zu viele, wird kein Video erstellt.</p>
	              <p>Monatlich/Jährlich verwenden standardmäßig Bilder um 12:00 Uhr (±90 Min.). Mit <strong>Sonnenuntergang</strong> liegt das Fenster an jedem Tag um dessen Sonnenuntergang und wandert so mit der Jahreszeit.</p>
	            </div>

	              <?php if ($formMessage !== null && !in_array($submittedAction, ["rebuild-jobs", "publish-camera"], true)): ?>
                <p>
                  <?= htmlspecialchars($formMessage, ENT_QUOTES, "UTF-8") ?>
                </p>
	                <?php endif; ?>
	            <form method="post" id="create-video-form"
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

	              <p id="daylight-buffer-note" hidden>
	                <?php if ($savedDaylightBuffer !== null): ?>
	                  Zeitpuffer: <strong><?= $savedDaylightBuffer ?> Minuten</strong> (aus den Einstellungen)
	                <?php else: ?>
	                  Der Zeitpuffer aus den Einstellungen konnte nicht gelesen werden.
	                <?php endif; ?>
	              </p>

	              <fieldset id="interval-window-fieldset" hidden>
	                <legend>Zeitfenster</legend>

	                <label>
	                  <input type="radio" name="interval_window" value="default" checked>
	                  Mittag (Standard, 12:00 Uhr ±90 Min.)
	                </label>

	                <label>
	                  <input type="radio" name="interval_window" value="sunset">
	                  Sonnenuntergang
	                </label>
	              </fieldset>

	              <fieldset id="window-tolerance-fieldset" hidden>
	                <legend>Fensterbreite um den Sonnenuntergang</legend>

	                <label>
	                  <input type="radio" name="window_tolerance_minutes" value="30">
	                  ±30 Min.
	                </label>

	                <label>
	                  <input type="radio" name="window_tolerance_minutes" value="60" checked>
	                  ±60 Min.
	                </label>

	                <label>
	                  <input type="radio" name="window_tolerance_minutes" value="90">
	                  ±90 Min.
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

	              <?php if ($cameraIsBlurred): ?>
	                <p id="blur-note">
	                  Hinweis: Bei dieser Kamera werden die Bilder vorher automatisch verpixelt. Die
	                  Erstellung dauert deshalb deutlich länger.
	                </p>
	              <?php endif; ?>

	              <button type="submit">
	                Video erstellen
	              </button>

	            </form>
	          </section>
	        </div>
    <?php endif; ?>
	  </main>

	  <?php $deleteDialogTitle = "Video löschen"; ?>
	  <?php require __DIR__ . "/../src/components/confirm-delete.php"; ?>

	<script>
		// A job was started right before this page load: hand it to the shared job-watcher
		// (required right below), which polls it to completion from any page.
		const startedJob = <?= json_encode($startedJob, JSON_HEX_TAG | JSON_HEX_AMP) ?>;

		if (startedJob !== null) {
			sessionStorage.setItem("timelapsePendingJob", JSON.stringify(startedJob));
		}
	</script>

	  <?php require __DIR__ . "/../src/components/job-watcher.php"; ?>

	<?php if ($camera !== ""): ?>
	  <script>
		// After a background delete (confirm-delete.php): drop the entry and keep its list open.
		// Deleting the video that is playing reloads the page without it, same list open.
		const playingVideo = <?= json_encode(
			$selectedVideo !== null && $selectedSource === "manual"
				? ["job" => $selectedJob, "filename" => $selectedVideo["filename"]]
				: null,
			JSON_HEX_TAG | JSON_HEX_AMP,
		) ?>;

		document.addEventListener("deleted", (event) => {
			const form = event.target;
			const job = form.elements.job.value;
			const filename = form.elements.video.value;

			if (playingVideo !== null && playingVideo.job === job && playingVideo.filename === filename) {
				window.location.replace("/camera.php?" + new URLSearchParams({
					camera: form.elements.camera.value,
					job,
					deleted: "1",
				}));
				return;
			}

			// Same green message as after a reload with ?deleted=1; any full page load drops it again.
			const deletedMessage = document.querySelector("#delete-success-message");
			deletedMessage.textContent = event.detail.message;
			deletedMessage.hidden = false;

			const item = form.closest("li");
			const next = item.nextElementSibling ?? item.previousElementSibling;
			const details = item.closest("details");
			const source = item.closest("[data-video-source]");
			item.remove();

			// Last video of this job type: its group goes, and an empty list says so.
			let empty = null;

			if (next === null) {
				details.remove();

				if (source.querySelector("details") === null) {
					empty = document.createElement("p");
					empty.textContent = source.dataset.emptyText;
					empty.tabIndex = -1;
					source.append(empty);
				}
			}

			// Keep the keyboard in the list instead of dropping it to the page start.
			(next?.querySelector("a") ?? source.querySelector("summary") ?? empty)?.focus();
		});

	    const videoWasDeleted = <?= json_encode($videoWasDeleted, JSON_HEX_TAG | JSON_HEX_AMP) ?>;

	    // Drop ?deleted=1 from the URL so a later refresh doesn't re-show the message.
	    if (videoWasDeleted) {
	      const url = new URL(window.location.href);
	      url.searchParams.delete("deleted");
	      window.history.replaceState(null, "", url);
	    }

	    // Monthly/Yearly use no daylight buffer, so the note names it only for Daily/Weekly (display
	    // only). The list comes from PHP ($daylightBufferJobs), so it cannot drift from the server.
	    const daylightBufferJobs = <?= json_encode($daylightBufferJobs, JSON_HEX_TAG | JSON_HEX_AMP) ?>;
	    const daylightBufferNote = document.querySelector("#daylight-buffer-note");
	    const jobRadios = document.querySelectorAll('input[name="job"]');

	    // Same idea for the Monthly/Yearly window: display convenience only, the
	    // server drops any window value submitted with Daily/Weekly.
	    const intervalWindowJobs = <?= json_encode($intervalWindowJobs, JSON_HEX_TAG | JSON_HEX_AMP) ?>;
	    const intervalWindowFieldset = document.querySelector("#interval-window-fieldset");
	    const windowToleranceFieldset = document.querySelector("#window-tolerance-fieldset");
	    const windowRadios = document.querySelectorAll('input[name="interval_window"]');

	    function updateDaylightBufferVisibility() {
	      const checkedJob = document.querySelector('input[name="job"]:checked');
	      const showBuffer = checkedJob !== null && daylightBufferJobs.includes(checkedJob.value);
	      const showWindow = checkedJob !== null && intervalWindowJobs.includes(checkedJob.value);
	      const checkedWindow = document.querySelector('input[name="interval_window"]:checked');
	      const showTolerance = showWindow && checkedWindow !== null && checkedWindow.value === "sunset";

	      daylightBufferNote.hidden = !showBuffer;
	      intervalWindowFieldset.hidden = !showWindow;
	      windowToleranceFieldset.hidden = !showTolerance;
	    }

	    jobRadios.forEach((radio) => {
	      radio.addEventListener("change", updateDaylightBufferVisibility);
	    });

	    windowRadios.forEach((radio) => {
	      radio.addEventListener("change", updateDaylightBufferVisibility);
	    });

	    updateDaylightBufferVisibility();

		// One job at a time: the button is disabled from the click until the job this tab started
		// is over (job-watcher.php enables it again). pageshow also runs on the first load and
		// when the browser restores the page from its back/forward cache.
		const createButton = document.querySelector('#create-video-form button[type="submit"]');
		document.querySelector("#create-video-form").addEventListener("submit", () => {
			createButton.disabled = true;
		});
		window.addEventListener("pageshow", () => {
			createButton.disabled = sessionStorage.getItem("timelapsePendingJob") !== null;
		});

		// The rebuild button stays disabled until a video type is ticked, and while this tab's own job
		// runs. The job watcher fires "change" on the form when a job is over; the server refuses an
		// empty selection anyway.
		const rebuildForm = document.querySelector("#rebuild-form");
		const rebuildButton = rebuildForm.querySelector('button[type="submit"]');

		function updateRebuildButton() {
			const anyTicked = rebuildForm.querySelector('input[name="rebuild_jobs[]"]:checked') !== null;
			rebuildButton.disabled = !anyTicked || sessionStorage.getItem("timelapsePendingJob") !== null;
		}

		rebuildForm.addEventListener("change", updateRebuildButton);
		rebuildForm.addEventListener("submit", () => {
			rebuildButton.disabled = true;
		});
		window.addEventListener("pageshow", updateRebuildButton);

		// The upload button stays disabled until the confirmation is ticked, and while this tab's own
		// job runs. The server only accepts the exact confirmation; this is a convenience.
		const publishForm = document.querySelector("#publish-form");

		if (publishForm !== null) {
			const publishButton = publishForm.querySelector('button[type="submit"]');
			const updatePublishButton = () => {
				const confirmed = publishForm.querySelector('input[name="confirm"]:checked') !== null;
				publishButton.disabled = !confirmed || sessionStorage.getItem("timelapsePendingJob") !== null;
			};

			publishForm.addEventListener("change", updatePublishButton);
			publishForm.addEventListener("submit", () => {
				publishButton.disabled = true;
			});
			window.addEventListener("pageshow", updatePublishButton);
		}

		// Yesterday by default and nothing after today, in the browser's (local) time.
		function isoDate(date) {
			return [
				date.getFullYear(),
				String(date.getMonth() + 1).padStart(2, "0"),
				String(date.getDate()).padStart(2, "0"),
			].join("-");
		}

		const targetDateInput = document.querySelector("#target-date");
		const today = new Date();
		targetDateInput.max = isoDate(today);

		if (targetDateInput.value === "") {
			const yesterday = new Date(today);
			yesterday.setDate(yesterday.getDate() - 1);
			targetDateInput.value = isoDate(yesterday);
		}
	  </script>
	<?php endif; ?>
	</body>
</html>
