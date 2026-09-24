<?php

declare(strict_types=1);
session_start();

require_once __DIR__ . "/../src/video-library.php";
require_once __DIR__ . "/../src/job-runner.php";

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

$formMessage = null;
$formIsValid = false;
$activeJobId = null;
$activeJobType = null;
$activeTargetDate = null;

if ($_SERVER["REQUEST_METHOD"] === "POST") {
	$submittedToken = $_POST["csrf_token"] ?? null;
	$submittedCamera = $_POST["camera"] ?? null;
	$submittedJob = $_POST["job"] ?? null;
	$submittedDate = $_POST["target_date"] ?? null;

	if (
		!is_string($submittedToken)
		|| !hash_equals($csrfToken, $submittedToken)
	) {
		$formMessage = "The request token is invalid.";
	} elseif (
		!is_string($submittedCamera)
		|| $submittedCamera !== $camera
		|| !in_array($submittedCamera, $availableCameras, true)
	) {
		$formMessage = "The selected camera is invalid.";
	} elseif (
		!is_string($submittedJob)
		|| !in_array($submittedJob, $allowedJobs, true)
	) {
		$formMessage = "The selected job is invalid.";
	} elseif (
		!is_string($submittedDate)
		|| !isValidIsoDate($submittedDate)
	) {
		$formMessage = "The target date is invalid.";
		} else {
			$formIsValid = true;
			$jobResult = startVideoJob(
				$submittedJob,
				$submittedDate,
				$submittedCamera,
			);
			$formMessage = $jobResult["message"];
			$activeJobId = $jobResult["jobId"];

			if ($jobResult["started"]) {
				$activeJobType = $submittedJob;
				$activeTargetDate = $submittedDate;
			}
		}
}

?>

<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Camera</title>
</head>
<body>
  <header>
    <nav aria-label="Main navigation">
      <a href="/">Back to cameras</a>
    </nav>
    <dl aria-label="Storage usage">
	    <div>
		    <dt>Total storage</dt>
		    <dd><?= htmlspecialchars($storage["total"], ENT_QUOTES, "UTF-8") ?></dd>
	    </div>
	    <div>
		    <dt>Storage used</dt>
		    <dd><?= htmlspecialchars($storage["used"], ENT_QUOTES, "UTF-8") ?></dd>
	    </div>
	    <div>
		    <dt>Available storage</dt>
		    <dd><?= htmlspecialchars($storage["available"], ENT_QUOTES, "UTF-8") ?></dd>
	    </div>
    </dl>
  </header>
  <main>
    <?php if ($camera === ""): ?>
      <h1>Camera not found</h1>
    <?php else: ?>
	      <h1><?= htmlspecialchars($camera, ENT_QUOTES, "UTF-8")?></h1>
	        <div>
	          <section>
	            <h2>Video player</h2>

	            <?php if ($selectedVideo === null): ?>
	              <p>Select a video from the library.</p>
	            <?php else: ?>
	              <video controls preload="metadata" width="720">
	                <source
	                  src="<?= htmlspecialchars($selectedVideo["url"], ENT_QUOTES, "UTF-8") ?>"
	                  type="video/mp4"
	                >
	                Your browser does not support MP4 video playback.
	              </video>
	            <?php endif; ?>
	          </section>

	          <section>
            <h2>Manual Videos</h2>
            <?php if ($manualVideos === []): ?>
              <p>no manual videos found</p>
            <?php else: ?>
              <?php foreach ($manualVideos as $job => $videos): ?>
                <section>
                  <h3>
                    <?= htmlspecialchars(ucfirst($job), ENT_QUOTES, "UTF-8") ?>
                  </h3>
                    <ul>

	                      <?php foreach ($videos as $video): ?>
	                        <li>
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
	                              $video["filename"],
	                              ENT_QUOTES,
	                              "UTF-8",
	                            ) ?>
	                          </a>
                      </li>
                      <?php endforeach; ?>
                    </ul>
                </section>
              <?php endforeach; ?>
            <?php endif; ?>
          </section>
	          <section>
	            <h2>Create historical video</h2>
	              <?php if ($formMessage !== null): ?>
                <p>
                  <?= htmlspecialchars($formMessage, ENT_QUOTES, "UTF-8") ?>
                </p>
	                <?php endif; ?>
	              <?php if ($activeJobId !== null): ?>
	                <p id="job-live-status" role="status" aria-live="polite">
	                  Video creation is running.
	                </p>
	              <?php endif; ?>
	            <form method="post"
                    action="/camera.php?camera=<?= rawurlencode($camera) ?>">
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
	                <legend>Job type</legend>

	                <label>
	                  <input type="radio" name="job" value="daily" required>
	                  Daily
	                </label>

	                <label>
	                  <input type="radio" name="job" value="weekly">
	                  Weekly
	                </label>

	                <label>
	                  <input type="radio" name="job" value="monthly">
	                  Monthly
	                </label>

	                <label>
	                  <input type="radio" name="job" value="yearly">
	                  Yearly
	                </label>
	              </fieldset>

	              <div>
	                <label for="target-date">Target date</label>
	                <input
	                  id="target-date"
	                  type="date"
	                  name="target_date"
	                  required
	                >
	              </div>

	              <button type="submit">
	                Create video
	              </button>

	            </form>
	          </section>
	        </div>
    <?php endif; ?>
	  </main>

	  <dialog id="job-result-dialog">
	    <h2 id="job-result-title">Video job finished</h2>
	    <p id="job-result-message"></p>

	    <form method="dialog">
	      <button type="submit">Close</button>
	    </form>
	  </dialog>

	  <script>
	    const activeJobId = <?= json_encode($activeJobId, JSON_HEX_TAG | JSON_HEX_AMP) ?>;
	    const activeJobType = <?= json_encode($activeJobType, JSON_HEX_TAG | JSON_HEX_AMP) ?>;
	    const activeTargetDate = <?= json_encode($activeTargetDate, JSON_HEX_TAG | JSON_HEX_AMP) ?>;
	    const currentCamera = <?= json_encode($camera, JSON_HEX_TAG | JSON_HEX_AMP) ?>;
	    const resultStorageKey = "timelapseJobResult";
	    const resultDialog = document.querySelector("#job-result-dialog");
	    const resultTitle = document.querySelector("#job-result-title");
	    const resultMessage = document.querySelector("#job-result-message");

	    function showJobResult(result) {
	      if (result.status === "completed") {
	        resultTitle.textContent = "Video created";
	        resultMessage.textContent = `${result.job} for ${result.targetDate} was created successfully.`;
	      } else {
	        resultTitle.textContent = "Video creation failed";
	        resultMessage.textContent = `${result.job} for ${result.targetDate} could not be created. Check the application log.`;
	      }

	      if (typeof resultDialog.showModal === "function") {
	        resultDialog.showModal();
	      }
	    }

	    const storedResult = sessionStorage.getItem(resultStorageKey);

	    if (storedResult !== null) {
	      sessionStorage.removeItem(resultStorageKey);

	      try {
	        showJobResult(JSON.parse(storedResult));
	      } catch (error) {
	        console.error("Could not read the stored video-job result.", error);
	      }
	    }

	    if (activeJobId !== null) {
	      const liveStatus = document.querySelector("#job-live-status");
	      let consecutiveErrors = 0;

	      async function pollJobStatus() {
	        try {
	          const response = await fetch(
	            `/job-status.php?id=${encodeURIComponent(activeJobId)}`,
	            { cache: "no-store" },
	          );

	          if (!response.ok) {
	            throw new Error(`Status request failed with HTTP ${response.status}.`);
	          }

	          const result = await response.json();
	          consecutiveErrors = 0;

	          if (result.status === "running") {
	            liveStatus.textContent = `${activeJobType} for ${activeTargetDate} is running.`;
	            window.setTimeout(pollJobStatus, 5000);
	            return;
	          }

	          if (result.status === "completed" || result.status === "failed") {
	            sessionStorage.setItem(
	              resultStorageKey,
	              JSON.stringify({
	                status: result.status,
	                job: activeJobType,
	                targetDate: activeTargetDate,
	              }),
	            );

	            window.location.href = `/camera.php?camera=${encodeURIComponent(currentCamera)}`;
	            return;
	          }

	          throw new Error("The server returned an unknown job status.");
	        } catch (error) {
	          consecutiveErrors += 1;

	          if (consecutiveErrors >= 3) {
	            liveStatus.textContent = "Job status could not be checked. Refresh the page later.";
	            console.error("Video-job polling stopped.", error);
	            return;
	          }

	          window.setTimeout(pollJobStatus, 5000);
	        }
	      }

	      pollJobStatus();
	    }
	  </script>
	</body>
</html>
