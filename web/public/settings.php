<?php

declare(strict_types=1);
session_start();

require_once __DIR__ . "/../src/video-library.php";
require_once __DIR__ . "/../src/settings-runner.php";
require_once __DIR__ . "/../src/settings-form.php";

$storage = getStorageUsage();
// The header marks its own link as the current page.
$currentPage = "settings";
$currentTab = "general";

if (!isset($_SESSION["csrf_token"])) {
	$_SESSION["csrf_token"] = bin2hex(random_bytes(32));
}

$csrfToken = $_SESSION["csrf_token"];

$knownCameras = settingsKnownCameras();
$baseConfig = readBaseConfig();
$state = settingsFormState(readProjectConfig(), $knownCameras);
// What the restore buttons go back to: the same form state, from config.json alone.
$defaultState = settingsFormState($baseConfig, $knownCameras);
$savedMtime = readSettingsMtime();
// What the page hands back on save. After a refusal because the file changed it stays the OLD
// value, so a second try without reloading is refused again.
$pageMtime = $savedMtime;

$messages = [];
$fieldErrors = [];

if ($_SERVER["REQUEST_METHOD"] === "POST") {
	$submittedToken = $_POST["csrf_token"] ?? null;
	$submittedMtime = $_POST["loaded_mtime"] ?? null;

	// After any refusal the page shows what was typed.
	$state = settingsFormStateFromPost($_POST);

	if (!is_string($submittedToken) || !hash_equals($csrfToken, $submittedToken)) {
		$messages[] = "Die Anfrage ist ungültig (Sicherheitstoken).";

	// Only the exact string "yes" confirms: the Save button sends it, a crafted request can send
	// anything, also an array.
	} elseif (($_POST["confirm"] ?? null) !== "yes") {
		$messages[] = "Bitte das Speichern mit der Schaltfläche bestätigen.";

	} elseif (!is_string($submittedMtime) || preg_match('/^[0-9]{1,12}$/D', $submittedMtime) !== 1) {
		$messages[] = "Die Anfrage ist ungültig (Seitenstand).";

	} else {
		[$values, $problems] = settingsValuesFromPost($_POST, $knownCameras);

		if ($problems !== []) {
			$messages = $problems;

		} else {
			$result = saveSettings($values, (int) $submittedMtime);

			if ($result["status"] === "saved") {
				// Post/Redirect/Get: a reload must not send the form again.
				$_SESSION["settings_saved"] = true;
				header("Location: /settings.php");

				exit;
			}

			if ($result["status"] === "stale") {
				$pageMtime = (int) $submittedMtime;
				$messages[] = "Die Einstellungen wurden inzwischen geändert, bitte Seite neu laden.";

			} elseif ($result["status"] === "invalid") {
				[$fieldErrors, $messages] = settingsSplitErrors($result["errors"]);

			} else {
				$messages = $result["errors"];
			}
		}
	}
}

$justSaved = ($_SESSION["settings_saved"] ?? false) === true;
unset($_SESSION["settings_saved"]);

// The summary above the form: messages without a field, then one link per field with a problem.
$fieldLabels = [];

foreach (settingsScalarFields() as $field) {
	$fieldLabels[$field["key"]] = $field["label"];
}

$hasProblems = $messages !== [] || $fieldErrors !== [];
$lastSaved = formatSettingsTime($savedMtime);

$fieldsOf = static fn(string $group): array => array_values(array_filter(
	settingsScalarFields(),
	static fn(array $field): bool => $field["group"] === $group,
));

?>

<!DOCTYPE html>
<html lang="de">
<head>
	<meta charset="UTF-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<link rel="stylesheet" href="/style.css">
	<title>Einstellungen – Zeitraffer</title>
</head>
<body>
	<header>
		<?php require __DIR__ . "/../src/components/header.php"; ?>
	</header>
	<main>
		<h1>Einstellungen</h1>

		<?php require __DIR__ . "/../src/components/settings-tabs.php"; ?>

		<div class="job-instructions settings-intro">
			<p>Hier lassen sich die Werte ändern, die für alle Kameras gelten. Eine Änderung gilt ab dem nächsten Auftrag, ein gerade laufender Auftrag ist nicht betroffen. Neue Videos nutzen die neue Qualität, bestehende bleiben unverändert.</p>
		</div>

		<?php if ($justSaved): ?>
			<p class="delete-success-message" role="status">Gespeichert. Die Einstellungen gelten ab dem nächsten Auftrag.</p>
		<?php endif; ?>

		<?php if ($hasProblems): ?>
			<div class="form-message" role="alert" id="settings-problems">
				<ul class="settings-problems">
					<?php foreach ($messages as $message): ?>
						<li><?= settingsHtml($message) ?></li>
					<?php endforeach; ?>
					<?php foreach ($fieldErrors as $key => $message): ?>
						<li><a href="#<?= settingsHtml(settingsFieldId($key)) ?>"><?= settingsHtml($fieldLabels[$key] . ": " . $message) ?></a></li>
					<?php endforeach; ?>
				</ul>
			</div>
		<?php endif; ?>

		<form method="post" action="/settings.php" class="settings-form">
			<input type="hidden" name="csrf_token" value="<?= settingsHtml($csrfToken) ?>">
			<input type="hidden" name="loaded_mtime" value="<?= (int) $pageMtime ?>">

			<fieldset class="settings-group">
				<legend>Videoqualität</legend>
				<?php renderSettingsDefaultButton("Videoqualität"); ?>
				<?php foreach ($fieldsOf("quality") as $field): ?>
					<?php renderSettingsField($field, $state, $baseConfig, $fieldErrors); ?>
				<?php endforeach; ?>
			</fieldset>

			<fieldset class="settings-group">
				<legend>Kameras</legend>
				<?php renderSettingsDefaultButton("Kameras"); ?>
				<p class="settings-hint">Angehakte Kameras werden nachts verarbeitet. Eine abgewählte Kamera wird nicht mehr gebaut und verschwindet sofort aus der Kameraliste dieser Weboberfläche. Eine wieder angehakte Kamera erscheint dort, und hier, nach dem nächsten Nachtlauf wieder. Mindestens eine Kamera muss angehakt bleiben.</p>
				<?php renderSettingsCameraBoxes("process_cameras", $knownCameras, $state["processed"], $defaultState["processed"]); ?>
			</fieldset>

			<fieldset class="settings-group">
				<legend>Highlights (Flagger)</legend>
				<?php renderSettingsDefaultButton("Highlights (Flagger)"); ?>
				<p class="settings-hint">Kameras, auf denen nach Flugzeugen, Vögeln und Drachen gesucht wird.</p>
				<?php renderSettingsCameraBoxes("flagger_cameras", $knownCameras, $state["flagger"], $defaultState["flagger"]); ?>
				<?php foreach ($fieldsOf("flagger") as $field): ?>
					<?php renderSettingsField($field, $state, $baseConfig, $fieldErrors); ?>
				<?php endforeach; ?>
			</fieldset>

			<fieldset class="settings-group">
				<legend>Zeitfenster und Abdeckung</legend>
				<?php renderSettingsDefaultButton("Zeitfenster und Abdeckung"); ?>
				<?php foreach ($fieldsOf("daylight") as $field): ?>
					<?php renderSettingsField($field, $state, $baseConfig, $fieldErrors); ?>
				<?php endforeach; ?>
			</fieldset>

			<fieldset class="settings-group">
				<legend>Tageslicht-Puffer je Monat (automatische Videos, Minuten)</legend>
				<?php renderSettingsDefaultButton("Tageslicht-Puffer je Monat"); ?>
				<p class="settings-hint">Wie viele Minuten vor Sonnenaufgang und nach Sonnenuntergang noch Bilder verwendet werden.</p>
				<div class="settings-months">
					<?php foreach ($fieldsOf("months") as $field): ?>
						<?php renderSettingsField($field, $state, $baseConfig, $fieldErrors); ?>
					<?php endforeach; ?>
				</div>
			</fieldset>

			<fieldset class="settings-group">
				<legend>Protokolle</legend>
				<?php renderSettingsDefaultButton("Protokolle"); ?>
				<?php foreach ($fieldsOf("logs") as $field): ?>
					<?php renderSettingsField($field, $state, $baseConfig, $fieldErrors); ?>
				<?php endforeach; ?>
			</fieldset>

			<p class="settings-hint" id="settings-default-note" role="status" hidden></p>

			<div class="settings-bar">
				<p class="settings-saved">
					<?= $lastSaved !== "" ? "Zuletzt gespeichert: " . settingsHtml($lastSaved) : "Noch nicht auf dieser Seite gespeichert." ?>
				</p>
				<button type="reset" class="settings-reset">Änderungen verwerfen</button>
				<button type="button" class="settings-reset" data-default-all hidden>Alles auf Standard</button>
				<button type="submit" name="confirm" value="yes">Speichern</button>
			</div>
		</form>
	</main>

	<script>
		(() => {
			const form = document.querySelector(".settings-form");
			const note = document.querySelector("#settings-default-note");

			// Fills the fields of one scope with their Standard (the config.json value). Nothing is
			// saved: the Save button stores it, and a value equal to the Standard drops its override.
			const restoreDefaults = (scope, what) => {
				scope.querySelectorAll("[data-default]").forEach((input) => {
					input.value = input.dataset.default;
					// A script sets no "input" event by itself: announce it, so a slider follows.
					input.dispatchEvent(new Event("input"));
				});

				scope.querySelectorAll("[data-default-checked]").forEach((input) => {
					input.checked = input.dataset.defaultChecked === "1";
				});

				note.textContent = `${what}: Standardwerte eingetragen. Zum Übernehmen bitte speichern.`;
				note.hidden = false;
			};

			// A slider only helps the mouse: the field is the real control, so both follow each other.
			// The slider of a time field counts minutes since midnight, the slider of a number field the
			// number itself.
			const toMinutes = (text) => {
				const [hours, minutes] = text.split(":").map(Number);

				return hours * 60 + minutes;
			};
			const toClock = (total) =>
				`${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;

			const syncSlider = (range) => {
				const field = form.querySelector(`#${range.dataset.sliderFor}`);

				if (field.value !== "") {
					range.value = field.type === "time" ? String(toMinutes(field.value)) : field.value;
				}
			};

			form.querySelectorAll("[data-slider-for]").forEach((range) => {
				const field = form.querySelector(`#${range.dataset.sliderFor}`);

				range.hidden = false;
				range.addEventListener("input", () => {
					field.value = field.type === "time" ? toClock(Number(range.value)) : range.value;
				});
				field.addEventListener("input", () => syncSlider(range));
				syncSlider(range);
			});

			// Without JavaScript the buttons stay hidden: they would do nothing.
			form.querySelectorAll("[data-default-group]").forEach((button) => {
				const fieldset = button.closest("fieldset");

				button.hidden = false;
				button.addEventListener("click", () => {
					restoreDefaults(fieldset, fieldset.querySelector("legend").textContent);
				});
			});

			const allButton = form.querySelector("[data-default-all]");

			allButton.hidden = false;
			allButton.addEventListener("click", () => restoreDefaults(form, "Alle Abschnitte"));

			// "Änderungen verwerfen" returns to the loaded values, so the note no longer applies.
			form.addEventListener("reset", () => {
				note.hidden = true;
				// The fields go back to their loaded values after this event, so look then.
				setTimeout(() => form.querySelectorAll("[data-slider-for]").forEach(syncSlider), 0);
			});
		})();
	</script>

	<?php require __DIR__ . "/../src/components/job-watcher.php"; ?>
</body>
</html>
