<?php

declare(strict_types=1);
session_start();

require_once __DIR__ . "/../src/video-library.php";
require_once __DIR__ . "/../src/settings-runner.php";
require_once __DIR__ . "/../src/privacy-form.php";

$storage = getStorageUsage();
// The header marks the settings area as the current page, the tab strip its own tab.
$currentPage = "settings";
$currentTab = "verpixelung";

if (!isset($_SESSION["csrf_token"])) {
	$_SESSION["csrf_token"] = bin2hex(random_bytes(32));
}

$csrfToken = $_SESSION["csrf_token"];

$config = readProjectConfig();
$baseConfig = readBaseConfig();
$basePrivacy = is_array($baseConfig["privacy"] ?? null) ? $baseConfig["privacy"] : [];
$baseBlurCameras = cameraNames($basePrivacy["blur_cameras"] ?? []);
$knownCameras = privacyKnownCameras($config);
$state = privacyFormState($config);
// What the restore buttons go back to: the same form state, from config.json alone.
$defaultState = privacyFormState($baseConfig);
$savedMtime = readSettingsMtime("privacy");
// What the page hands back on save. After a refusal because the file changed it stays the OLD
// value, so a second try without reloading is refused again.
$pageMtime = $savedMtime;

$messages = [];
$fieldErrors = [];

if ($_SERVER["REQUEST_METHOD"] === "POST") {
	$submittedToken = $_POST["csrf_token"] ?? null;
	$submittedMtime = $_POST["loaded_mtime"] ?? null;

	// After any refusal the page shows what was typed.
	$state = privacyFormStateFromPost($_POST);

	if (!is_string($submittedToken) || !hash_equals($csrfToken, $submittedToken)) {
		$messages[] = "Die Anfrage ist ungültig (Sicherheitstoken).";

	// This is a privacy setting: only the exact string "yes" confirms. The dialog (or the tick box
	// without JavaScript) sends it, a crafted request can send anything, also an array.
	} elseif (($_POST["confirm_privacy"] ?? null) !== "yes") {
		$messages[] = "Bitte die Änderungen bestätigen.";

	} elseif (!is_string($submittedMtime) || preg_match('/^[0-9]{1,12}$/D', $submittedMtime) !== 1) {
		$messages[] = "Die Anfrage ist ungültig (Seitenstand).";

	} else {
		[$values, $problems] = privacyValuesFromPost($_POST, $knownCameras);

		if ($problems !== []) {
			$messages = $problems;

		} else {
			$result = saveSettings($values, (int) $submittedMtime, "privacy");

			if ($result["status"] === "saved") {
				// Post/Redirect/Get: a reload must not send the form again.
				$_SESSION["privacy_saved"] = true;
				header("Location: /verpixelung.php");

				exit;
			}

			if ($result["status"] === "stale") {
				$pageMtime = (int) $submittedMtime;
				$messages[] = "Die Einstellungen wurden inzwischen geändert, bitte Seite neu laden.";

			} elseif ($result["status"] === "invalid") {
				[$fieldErrors, $messages] = privacySplitErrors($result["errors"]);

			} else {
				$messages = $result["errors"];
			}
		}
	}
}

$justSaved = ($_SESSION["privacy_saved"] ?? false) === true;
unset($_SESSION["privacy_saved"]);

$hasProblems = $messages !== [] || $fieldErrors !== [];
$lastSaved = formatSettingsTime($savedMtime);

// A blur value's Standard (null when config.json has none).
$standardOf = static fn(string $key): ?string => ($defaultState["floats"][$key] ?? "") !== "" ? $defaultState["floats"][$key] : null;

// What one camera goes back to: its score and top share in config.json, or "no minimum". Its boxes
// are data and have no Standard.
$cameraDefaults = static function (string $camera) use ($basePrivacy): array {
	$scores = is_array($basePrivacy["min_person_score"] ?? null) ? $basePrivacy["min_person_score"] : [];
	$tops = is_array($basePrivacy["ignore_top_share_per_camera"] ?? null) ? $basePrivacy["ignore_top_share_per_camera"] : [];
	$globalTop = privacyNumberText($basePrivacy["ignore_top_share"] ?? "");

	return [
		// Its own top share in config.json, else the one every camera gets from there.
		"top" => isset($tops[$camera]) ? privacyNumberText($tops[$camera]) : ($globalTop !== "" ? $globalTop : "0"),
		"score" => isset($scores[$camera]) ? privacyNumberText($scores[$camera]) : "0",
	];
};

?>

<!DOCTYPE html>
<html lang="de">
<head>
	<meta charset="UTF-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<link rel="stylesheet" href="/style.css">
	<title>Verpixelung – Zeitraffer</title>
</head>
<body>
	<header>
		<?php require __DIR__ . "/../src/components/header.php"; ?>
	</header>
	<main>
		<h1>Einstellungen</h1>

		<?php require __DIR__ . "/../src/components/storage-panel.php"; ?>

		<?php require __DIR__ . "/../src/components/settings-tabs.php"; ?>

		<div class="job-instructions settings-intro">
			<p>Hier wird eingestellt, wie Menschen auf den Kamerabildern unkenntlich gemacht werden. Das nennt man Verpixeln: Aus einem Gesicht werden grobe Kästchen, so erkennt niemand mehr, wer es ist.</p>
			<p>Das ist eine Datenschutz-Einstellung. Darum fragt die Seite vor dem Speichern noch einmal nach.</p>
		</div>

		<?php if ($justSaved): ?>
			<p class="delete-success-message" role="status">Gespeichert. Die Verpixelungs-Einstellungen gelten ab dem nächsten Auftrag.</p>
		<?php endif; ?>

		<?php if ($hasProblems): ?>
			<div class="form-message" role="alert" id="settings-problems">
				<ul class="settings-problems">
					<?php foreach ($messages as $message): ?>
						<li><?= settingsHtml($message) ?></li>
					<?php endforeach; ?>
					<?php foreach ($fieldErrors as $key => $message): ?>
						<li><a href="#<?= settingsHtml(privacyErrorTarget($key)) ?>"><?= settingsHtml(privacyErrorLabel($key) . ": " . $message) ?></a></li>
					<?php endforeach; ?>
				</ul>
			</div>
		<?php endif; ?>

		<form method="post" action="/verpixelung.php" class="settings-form" autocomplete="off">
			<input type="hidden" name="csrf_token" value="<?= settingsHtml($csrfToken) ?>">
			<input type="hidden" name="loaded_mtime" value="<?= (int) $pageMtime ?>">

			<fieldset class="settings-group">
				<legend>Welche Kameras werden verpixelt?</legend>
				<p class="settings-hint">Ein Haken bedeutet: Die Bilder dieser Kamera werden verpixelt, wenn Menschen darauf zu sehen sind. Eine neu angehakte Kamera wird ab der nächsten Nacht verpixelt, auch die Bilder von heute und den zwei Tagen davor.</p>
				<p class="privacy-important"><strong>Wichtig!</strong> Bei einer Kamera, die schon läuft und verpixelt, darf der Haken nicht weg. Sonst sind Menschen auf ihren Videos sofort wieder zu erkennen. Diese Kameras sind mit „läuft schon“ markiert.</p>
				<?php if (isset($fieldErrors["privacy.blur_cameras"])): ?>
					<p class="field-error" id="privacy-blur-cameras-error"><?= settingsHtml($fieldErrors["privacy.blur_cameras"]) ?></p>
				<?php endif; ?>
				<?php renderPrivacyCameraBoxes($knownCameras, $state["blur_cameras"], $baseBlurCameras, isset($fieldErrors["privacy.blur_cameras"])); ?>
			</fieldset>

			<fieldset class="settings-group">
				<legend>Wie wird verpixelt?</legend>
				<?php renderSettingsDefaultButton("Wie wird verpixelt?"); ?>
				<p class="settings-hint">Diese drei Werte gelten für alle Kameras. Sie wirken nur auf Bilder, die danach verpixelt werden. Bilder, die schon verpixelt sind, bleiben wie sie sind.</p>
				<?php foreach (privacyFloatFields() as $field): ?>
					<?php renderPrivacyNumber(
						privacyFieldId($field["key"]),
						"privacy[floats][" . $field["key"] . "]",
						$field,
						$state["floats"][$field["key"]],
						$standardOf($field["key"]),
						$fieldErrors[$field["key"]] ?? null,
					); ?>
				<?php endforeach; ?>
			</fieldset>

			<?php foreach ($state["cameras"] as $camera => $cameraState): ?>
				<?php $defaults = $cameraDefaults((string) $camera); ?>
				<fieldset class="settings-group privacy-camera" data-camera="<?= settingsHtml((string) $camera) ?>">
					<legend>Kamera <?= settingsHtml((string) $camera) ?></legend>
					<?php renderSettingsDefaultButton("Kamera " . $camera); ?>
					<?php renderPrivacyNumber(
						"privacy-score-" . $camera,
						"privacy[score][" . $camera . "]",
						privacyScoreField(),
						$cameraState["score"],
						$defaults["score"],
						$fieldErrors["privacy.min_person_score." . $camera] ?? null,
					); ?>
					<?php renderPrivacyNumber(
						"privacy-top-" . $camera,
						"privacy[top][" . $camera . "]",
						privacyTopField(),
						$cameraState["top"],
						$defaults["top"],
						$fieldErrors["privacy.ignore_top_share_per_camera." . $camera] ?? null,
					); ?>
					<?php renderPrivacyPreview((string) $camera, readPreviewInfo((string) $camera)); ?>
					<?php renderPrivacyBoxes(
						(string) $camera,
						$cameraState["boxes"],
						$fieldErrors["privacy.ignore_boxes." . $camera] ?? null,
					); ?>
				</fieldset>
			<?php endforeach; ?>

			<noscript>
				<label class="privacy-noscript-confirm">
					<input type="checkbox" name="confirm_privacy" value="yes">
					Ja, die Änderungen wurden geprüft und sollen gespeichert werden.
				</label>
			</noscript>

			<p class="settings-hint" id="settings-default-note" role="status" hidden></p>

			<div class="settings-bar">
				<p class="settings-saved">
					<?= $lastSaved !== "" ? "Zuletzt gespeichert: " . settingsHtml($lastSaved) : "Noch nicht auf dieser Seite gespeichert." ?>
				</p>
				<button type="reset" class="settings-reset">Änderungen verwerfen</button>
				<button type="button" class="settings-reset" data-default-all hidden>Alles auf Standard</button>
				<button type="submit">Speichern</button>
			</div>
		</form>

		<dialog id="privacy-confirm" aria-labelledby="privacy-confirm-title">
			<h2 id="privacy-confirm-title">Änderungen bestätigen</h2>
			<div class="privacy-important" id="privacy-confirm-important" hidden>
				<p><strong>Wichtig!</strong> Die Liste der verpixelten Kameras ändert sich:</p>
				<ul></ul>
			</div>
			<ul id="privacy-confirm-changes"></ul>
			<div class="privacy-confirm-buttons">
				<button type="button" class="settings-reset" data-confirm-cancel>Abbrechen</button>
				<button type="button" data-confirm-yes>Ja, speichern</button>
			</div>
		</dialog>
	</main>

	<script src="<?= settingsHtml(assetUrl("settings-common.js")) ?>"></script>
	<script src="<?= settingsHtml(assetUrl("verpixelung.js")) ?>"></script>
	<script src="<?= settingsHtml(assetUrl("storage-ring.js")) ?>"></script>

	<?php require __DIR__ . "/../src/components/job-watcher.php"; ?>
</body>
</html>
