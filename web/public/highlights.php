<?php

declare(strict_types=1);
session_start();

require_once __DIR__ . "/../src/highlights-library.php";
require_once __DIR__ . "/../src/highlight-delete.php";

$storage = getStorageUsage();
$highlightCameras = listHighlightCameras();
$flaggerCameras = getFlaggerCameras();

$periodLabels = [
	"1" => "Letzter Tag",
	"7" => "7 Tage",
	"30" => "30 Tage",
	"all" => "Alles",
];

$period = parseHighlightsPeriod($_GET["days"] ?? null);
$cameraFilter = is_string($_GET["camera"] ?? null) ? $_GET["camera"] : "";
$imageWasDeleted = ($_GET["deleted"] ?? null) === "1";

if (!isset($_SESSION["csrf_token"])) {
	$_SESSION["csrf_token"] = bin2hex(random_bytes(32));
}

$csrfToken = $_SESSION["csrf_token"];
$formMessage = null;

if ($_SERVER["REQUEST_METHOD"] === "POST") {
	$submittedToken = $_POST["csrf_token"] ?? null;
	$submittedCamera = $_POST["camera"] ?? null;
	$submittedDate = $_POST["date"] ?? null;
	$submittedFile = $_POST["file"] ?? null;

	// The filters to return to, with the same fallbacks as the GET parameters.
	$period = parseHighlightsPeriod($_POST["days"] ?? null);
	$cameraFilter = is_string($_POST["filter_camera"] ?? null) ? $_POST["filter_camera"] : "";

	if (
		!is_string($submittedToken)
		|| !hash_equals($csrfToken, $submittedToken)
	) {
		$formMessage = "Die Anfrage ist ungültig (Sicherheitstoken).";

	} elseif (
		!is_string($submittedCamera)
		|| !in_array($submittedCamera, $highlightCameras, true)
	) {
		$formMessage = "Die ausgewählte Kamera ist ungültig.";

	} elseif (!isListedHighlight($submittedCamera, $submittedDate, $submittedFile)) {
		$formMessage = "Das ausgewählte Bild wurde nicht gefunden.";

	} else {
		$deleteResult = deleteHighlightImage($submittedCamera, $submittedDate, $submittedFile);
		$formMessage = $deleteResult["message"];

		if ($deleteResult["deleted"]) {
			$query = ["days" => $period, "camera" => $cameraFilter, "deleted" => "1"];
			header("Location: /highlights.php?" . http_build_query($query));

			exit;
		}
	}
}

$shownCameras = $cameraFilter === ""
	? $highlightCameras
	: array_intersect($highlightCameras, [$cameraFilter]);

$since = highlightsSinceDate($period, highlightsToday());
$sections = [];

foreach ($shownCameras as $shownCamera) {
	$days = findHighlightDays($shownCamera, $since);

	$sections[] = [
		"camera" => $shownCamera,
		"days" => $days,
		"images" => array_sum(array_map(fn(array $day): int => count($day["items"]), $days)),
		"checked" => array_sum(array_column($days, "checked")),
	];
}

function escapeHtml(string $value): string
{
	return htmlspecialchars($value, ENT_QUOTES, "UTF-8");
}

// Position of the model's box in percent of the image, so it scales with the picture.
function highlightBoxStyle(array $item): string
{
	[$left, $top, $right, $bottom] = $item["box"];
	[$width, $height] = $item["imageSize"];

	return sprintf(
		"left: %.2F%%; top: %.2F%%; width: %.2F%%; height: %.2F%%",
		$left / $width * 100,
		$top / $height * 100,
		max(0, $right - $left) / $width * 100,
		max(0, $bottom - $top) / $height * 100,
	);
}

?>

<!DOCTYPE html>
<html lang="de">
<head>
	<meta charset="UTF-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<link rel="stylesheet" href="/style.css">
	<title>Highlights – Zeitraffer</title>
</head>
<body>
	<header>
		<?php require __DIR__ . "/../src/components/header.php"; ?>
	</header>
	<main class="highlights-page">
		<h1>Highlights</h1>

		<?php if ($imageWasDeleted): ?>
			<p class="delete-success-message">Bild erfolgreich gelöscht.</p>
		<?php endif; ?>

		<?php if ($formMessage !== null): ?>
			<p class="highlights-error" role="alert"><?= escapeHtml($formMessage) ?></p>
		<?php endif; ?>

		<form method="get" action="/highlights.php" class="highlights-filter">
			<label>
				Zeitraum
				<select name="days">
					<?php foreach ($periodLabels as $value => $label): ?>
						<option
							value="<?= escapeHtml((string) $value) ?>"
							<?= (string) $value === $period ? "selected" : "" ?>
						><?= escapeHtml($label) ?></option>
					<?php endforeach; ?>
				</select>
			</label>

			<label>
				Kamera
				<select name="camera">
					<option value="">Alle</option>
					<?php foreach ($highlightCameras as $optionCamera): ?>
						<option
							value="<?= escapeHtml($optionCamera) ?>"
							<?= $optionCamera === $cameraFilter ? "selected" : "" ?>
						><?= escapeHtml($optionCamera) ?></option>
					<?php endforeach; ?>
				</select>
			</label>

			<button type="submit">Anzeigen</button>
		</form>

		<p class="highlights-toggle">
			<label>
				<input type="checkbox" id="highlights-show-boxes">
				Markierung zeigen
			</label>
		</p>

		<?php if ($highlightCameras === []): ?>
			<p>Noch keine Highlights vorhanden.</p>
		<?php elseif ($sections === []): ?>
			<p>Für diese Kamera gibt es keine Highlights.</p>
		<?php endif; ?>

		<?php foreach ($sections as $sectionIndex => $section): ?>
			<section
				class="highlights-camera"
				aria-labelledby="highlights-camera-<?= $sectionIndex ?>"
			>
				<h2 id="highlights-camera-<?= $sectionIndex ?>">
					<?= escapeHtml($section["camera"]) ?>
					<span class="highlights-count">
						(<?= $section["images"] ?> <?= $section["images"] === 1 ? "Bild" : "Bilder" ?>)
					</span>
				</h2>

				<?php if ($section["days"] === []): ?>
					<p>
						<?= in_array($section["camera"], $flaggerCameras, true)
							? "Kein Bericht im Zeitraum."
							: "Keine Highlights im Zeitraum." ?>
					</p>
				<?php elseif ($section["images"] === 0): ?>
					<p>geprüft, nichts gefunden (<?= $section["checked"] ?> Bilder geprüft)</p>
				<?php else: ?>
					<?php foreach ($section["days"] as $day): ?>
						<h3>
							<?= escapeHtml(formatGermanDate($day["date"])) ?>
							· <?= $day["checked"] ?> Bilder geprüft
						</h3>

						<?php if ($day["items"] !== []): ?>
							<ul class="highlights-grid">
								<?php foreach ($day["items"] as $item): ?>
									<?php
									$guess = translateHighlightLabel($item["label"]) . "?";
									$percent = (int) round($item["score"] * 100);
									$viewerCaption = implode(" · ", [
										$section["camera"],
										formatGermanDate($day["date"]),
										"{$item["time"]} Uhr",
										$guess,
										"{$percent} %",
									]);
									?>
									<li>
										<figure>
											<div class="highlights-image">
												<a
													class="highlights-open"
													href="<?= escapeHtml($item["url"]) ?>"
													data-caption="<?= escapeHtml($viewerCaption) ?>"
													aria-label="Groß anzeigen: <?= escapeHtml($viewerCaption) ?>"
												>
													<img
														src="<?= escapeHtml($item["url"]) ?>"
														loading="lazy"
														width="<?= $item["imageSize"][0] ?>"
														height="<?= $item["imageSize"][1] ?>"
														alt="<?= escapeHtml("{$section["camera"]}, {$item["time"]} Uhr, {$guess}") ?>"
													>
												</a>
												<span
													class="highlights-box"
													style="<?= escapeHtml(highlightBoxStyle($item)) ?>"
													aria-hidden="true"
												></span>
											</div>

											<figcaption>
												<?= escapeHtml($item["time"]) ?> Uhr
												· <?= escapeHtml($guess) ?>
												· <?= $percent ?> %
											</figcaption>

											<div class="highlights-actions">
												<a
													href="<?= escapeHtml($item["url"]) ?>"
													download
													class="download-video-button"
													aria-label="<?= escapeHtml($item["file"]) ?> herunterladen"
												>
													<svg viewBox="0 0 24 24" aria-hidden="true">
														<path d="M12 16l-5-5h3V4h4v7h3l-5 5zm-7 2h14v2H5v-2z" />
													</svg>
													<span>Herunterladen</span>
												</a>

												<form
													method="post"
													action="/highlights.php"
													data-delete-confirm
													data-delete-name="<?= escapeHtml($item["file"]) ?>"
												>
													<input type="hidden" name="csrf_token" value="<?= escapeHtml($csrfToken) ?>">
													<input type="hidden" name="camera" value="<?= escapeHtml($section["camera"]) ?>">
													<input type="hidden" name="date" value="<?= escapeHtml($day["date"]) ?>">
													<input type="hidden" name="file" value="<?= escapeHtml($item["file"]) ?>">
													<input type="hidden" name="days" value="<?= escapeHtml($period) ?>">
													<input type="hidden" name="filter_camera" value="<?= escapeHtml($cameraFilter) ?>">

													<button
														type="submit"
														class="delete-video-button"
														aria-label="<?= escapeHtml($item["file"]) ?> löschen"
													>
														<svg viewBox="0 0 24 24" aria-hidden="true">
															<path d="M9 3h6l1 1h4v2H4V4h4l1-1zm-3 5h12l-1 13H7L6 8z" />
														</svg>
														<span>Löschen</span>
													</button>
												</form>
											</div>
										</figure>
									</li>
								<?php endforeach; ?>
							</ul>
						<?php endif; ?>
					<?php endforeach; ?>
				<?php endif; ?>
			</section>
		<?php endforeach; ?>
	</main>

	<?php $deleteDialogTitle = "Bild löschen"; ?>
	<?php require __DIR__ . "/../src/components/confirm-delete.php"; ?>

	<dialog id="highlights-viewer" class="highlights-viewer" aria-labelledby="highlights-viewer-caption">
		<figure>
			<div class="highlights-viewer-image">
				<img id="highlights-viewer-img" src="" alt="">
				<span id="highlights-viewer-box" class="highlights-box" aria-hidden="true"></span>
			</div>
			<figcaption id="highlights-viewer-caption"></figcaption>
		</figure>

		<div class="highlights-viewer-nav">
			<button type="button" id="highlights-viewer-prev">← Vorheriges</button>
			<button type="button" id="highlights-viewer-next">Nächstes →</button>
			<button type="button" id="highlights-viewer-close">Schließen</button>
		</div>
	</dialog>

	<?php require __DIR__ . "/../src/components/job-watcher.php"; ?>

	<script>
		// Apply a filter as soon as it changes; the "Anzeigen" button stays for browsers
		// without JavaScript.
		document.querySelectorAll(".highlights-filter select").forEach((select) => {
			select.addEventListener("change", () => select.form.requestSubmit());
		});

		const imageWasDeleted = <?= json_encode($imageWasDeleted, JSON_HEX_TAG | JSON_HEX_AMP) ?>;

		// Drop ?deleted=1 from the URL so a later refresh doesn't re-show the message.
		if (imageWasDeleted) {
			const url = new URL(window.location.href);
			url.searchParams.delete("deleted");
			window.history.replaceState(null, "", url);
		}

		// Full-size viewer: click an image, then step through all images on the page with the
		// buttons or the arrow keys. Esc and a click beside the image close it. Without
		// JavaScript (or <dialog>) the links simply open the full image.
		const viewer = document.querySelector("#highlights-viewer");
		const viewerImage = document.querySelector("#highlights-viewer-img");
		const viewerBox = document.querySelector("#highlights-viewer-box");
		const viewerCaption = document.querySelector("#highlights-viewer-caption");
		const viewerPrevious = document.querySelector("#highlights-viewer-prev");
		const viewerNext = document.querySelector("#highlights-viewer-next");
		const viewerLinks = Array.from(document.querySelectorAll("a.highlights-open"));
		let viewerIndex = 0;

		function showViewerImage(index) {
			viewerIndex = (index + viewerLinks.length) % viewerLinks.length;

			const link = viewerLinks[viewerIndex];
			const thumbnail = link.querySelector("img");
			const box = link.parentElement.querySelector(".highlights-box");

			viewerImage.src = link.href;
			viewerImage.alt = thumbnail.alt;
			viewerImage.width = thumbnail.width;
			viewerImage.height = thumbnail.height;
			viewerBox.setAttribute("style", box !== null ? box.getAttribute("style") : "");
			viewerCaption.textContent = link.dataset.caption;
		}

		if (typeof viewer.showModal === "function") {
			viewerPrevious.hidden = viewerLinks.length < 2;
			viewerNext.hidden = viewerLinks.length < 2;

			viewerLinks.forEach((link, index) => {
				link.addEventListener("click", (event) => {
					event.preventDefault();
					showViewerImage(index);
					viewer.showModal();
				});
			});

			viewerPrevious.addEventListener("click", () => showViewerImage(viewerIndex - 1));
			viewerNext.addEventListener("click", () => showViewerImage(viewerIndex + 1));
			document.querySelector("#highlights-viewer-close").addEventListener("click", () => viewer.close());

			viewer.addEventListener("keydown", (event) => {
				if (event.key === "ArrowLeft" && viewerLinks.length > 1) {
					showViewerImage(viewerIndex - 1);
				} else if (event.key === "ArrowRight" && viewerLinks.length > 1) {
					showViewerImage(viewerIndex + 1);
				}
			});

			// A click on the backdrop lands on the dialog element itself.
			viewer.addEventListener("click", (event) => {
				if (event.target === viewer) {
					viewer.close();
				}
			});

			// Back to the image that was opened (it may have scrolled out of view meanwhile).
			viewer.addEventListener("close", () => viewerLinks[viewerIndex].focus());
		}
	</script>
</body>
</html>
