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

// The blur values by group, each with its Standard (null when config.json has none).
$floatsOf = static fn(string $group): array => array_values(array_filter(
	privacyFloatFields(),
	static fn(array $field): bool => $field["group"] === $group,
));
$standardOf = static fn(string $key): ?string => ($defaultState["floats"][$key] ?? "") !== "" ? $defaultState["floats"][$key] : null;

// What one camera goes back to: its score and boxes in config.json, or "no minimum" and "no boxes".
$cameraDefaults = static function (string $camera) use ($basePrivacy): array {
	$scores = is_array($basePrivacy["min_person_score"] ?? null) ? $basePrivacy["min_person_score"] : [];
	$boxes = is_array($basePrivacy["ignore_boxes"] ?? null) ? $basePrivacy["ignore_boxes"] : [];

	return [
		"score" => isset($scores[$camera]) ? privacyNumberText($scores[$camera]) : "0",
		"boxes" => privacyBoxesForDefaults($boxes[$camera] ?? []),
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

		<form method="post" action="/verpixelung.php" class="settings-form">
			<input type="hidden" name="csrf_token" value="<?= settingsHtml($csrfToken) ?>">
			<input type="hidden" name="loaded_mtime" value="<?= (int) $pageMtime ?>">

			<fieldset class="settings-group">
				<legend>Welche Kameras werden verpixelt?</legend>
				<?php renderSettingsDefaultButton("Welche Kameras werden verpixelt?"); ?>
				<p class="settings-hint">Ein Haken bedeutet: Die Bilder dieser Kamera werden verpixelt, wenn Menschen darauf zu sehen sind. Eine neu angehakte Kamera wird ab der nächsten Nacht verpixelt, auch die Bilder von heute und den zwei Tagen davor.</p>
				<p class="privacy-important"><strong>Wichtig!</strong> Bei einer Kamera, die schon läuft und verpixelt, darf der Haken nicht weg. Sonst sind Menschen auf ihren Videos sofort wieder zu erkennen. Diese Kameras sind mit „läuft schon“ markiert.</p>
				<?php if (isset($fieldErrors["privacy.blur_cameras"])): ?>
					<p class="field-error" id="privacy-blur-cameras-error"><?= settingsHtml($fieldErrors["privacy.blur_cameras"]) ?></p>
				<?php endif; ?>
				<?php renderPrivacyCameraBoxes($knownCameras, $state["blur_cameras"], $baseBlurCameras); ?>
			</fieldset>

			<fieldset class="settings-group">
				<legend>Wie wird verpixelt?</legend>
				<?php renderSettingsDefaultButton("Wie wird verpixelt?"); ?>
				<p class="settings-hint">Diese drei Werte gelten für alle Kameras. Sie wirken nur auf Bilder, die danach verpixelt werden. Bilder, die schon verpixelt sind, bleiben wie sie sind.</p>
				<?php foreach ($floatsOf("blur") as $field): ?>
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

			<fieldset class="settings-group">
				<legend>Oberer Bildrand</legend>
				<?php renderSettingsDefaultButton("Oberer Bildrand"); ?>
				<?php foreach ($floatsOf("top") as $field): ?>
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
					<?php renderPrivacyBoxes(
						(string) $camera,
						$cameraState["boxes"],
						$defaults["boxes"],
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

	<script>
		(() => {
			const form = document.querySelector(".settings-form");
			const note = document.querySelector("#settings-default-note");
			const dialog = document.querySelector("#privacy-confirm");

			// A slider only helps the mouse: the number field is the real control, so both follow
			// each other.
			form.querySelectorAll("[data-slider-for]").forEach((range) => {
				const number = form.querySelector(`#${range.dataset.sliderFor}`);

				range.hidden = false;
				range.addEventListener("input", () => {
					number.value = range.value;
				});
				number.addEventListener("input", () => {
					range.value = number.value;
				});
			});

			// One more row of four box numbers, cloned from the camera's template.
			const addBoxRow = (container, cells = ["", "", "", ""]) => {
				const template = container.closest("fieldset").querySelector("[data-box-template]");
				const index = Number(container.dataset.nextIndex);

				container.dataset.nextIndex = String(index + 1);
				container.insertAdjacentHTML(
					"beforeend",
					template.innerHTML
						.replaceAll("__INDEX__", String(index))
						.replaceAll("__NUMBER__", String(index + 1)),
				);

				const row = container.lastElementChild;

				row.querySelectorAll("input").forEach((input, position) => {
					input.value = cells[position];
				});
				row.querySelector("[data-remove-box]").hidden = false;
			};

			// Without JavaScript these buttons stay hidden: they would do nothing.
			form.querySelectorAll("[data-remove-box]").forEach((button) => {
				button.hidden = false;
			});
			form.addEventListener("click", (event) => {
				const remove = event.target.closest("[data-remove-box]");

				if (remove !== null) {
					remove.closest(".privacy-box-row").remove();
				}
			});
			form.querySelectorAll("[data-add-box]").forEach((button) => {
				button.hidden = false;
				button.addEventListener("click", () => {
					addBoxRow(button.closest("fieldset").querySelector(".privacy-boxes"));
				});
			});

			// Fills the fields of one scope with their Standard (the config.json value). Nothing is
			// saved: the Save button and the dialog do that, and a value equal to the Standard
			// drops its override.
			const restoreDefaults = (scope, what) => {
				scope.querySelectorAll("[data-default]").forEach((input) => {
					input.value = input.dataset.default;
					input.dispatchEvent(new Event("input"));
				});

				scope.querySelectorAll("[data-default-checked]").forEach((input) => {
					input.checked = input.dataset.defaultChecked === "1";
				});

				scope.querySelectorAll("[data-default-boxes]").forEach((container) => {
					container.replaceChildren();
					JSON.parse(container.dataset.defaultBoxes).forEach((box) => {
						addBoxRow(container, box.map(String));
					});

					for (let blank = 0; blank < 3; blank += 1) {
						addBoxRow(container);
					}
				});

				note.textContent = `${what}: Standardwerte eingetragen. Zum Übernehmen bitte speichern.`;
				note.hidden = false;
			};

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
			});

			// What the dialog lists: everything that differs from what the page loaded with.
			const boxesText = (container) =>
				JSON.stringify(
					Array.from(container.querySelectorAll(".privacy-box-row"))
						.map((row) =>
							Array.from(row.querySelectorAll("input")).map((input) => input.value.trim()),
						)
						.filter((cells) => cells.some((cell) => cell !== "")),
				);
			const initial = new Map();

			form.querySelectorAll('input[name="blur_cameras[]"]').forEach((box) => {
				initial.set(box, box.checked);
			});
			form.querySelectorAll('input[type="number"][id]').forEach((input) => {
				initial.set(input, input.value);
			});
			form.querySelectorAll(".privacy-boxes").forEach((container) => {
				initial.set(container, boxesText(container));
			});

			const describeChanges = () => {
				const changes = [];
				const cameraChanges = [];

				initial.forEach((before, element) => {
					if (element.matches('input[type="checkbox"]')) {
						if (element.checked !== before) {
							const live = element.dataset.live === "1" ? " (läuft schon!)" : "";

							cameraChanges.push(
								element.checked
									? `${element.value}: wird ab der nächsten Nacht verpixelt`
									: `${element.value}: wird NICHT mehr verpixelt${live}`,
							);
						}
					} else if (element.matches(".privacy-boxes")) {
						if (boxesText(element) !== before) {
							changes.push(`${element.dataset.label}: Rahmen geändert`);
						}
					} else if (element.value !== before) {
						const label = form.querySelector(`label[for="${element.id}"]`).textContent.trim();

						changes.push(`${label} ${before} → ${element.value}`);
					}
				});

				return { changes, cameraChanges };
			};

			const showLines = (list, lines) => {
				list.replaceChildren(
					...lines.map((line) => {
						const item = document.createElement("li");

						item.textContent = line;

						return item;
					}),
				);
			};

			form.addEventListener("submit", (event) => {
				if (form.dataset.confirmed === "yes") {
					return;
				}

				event.preventDefault();

				const { changes, cameraChanges } = describeChanges();
				const important = dialog.querySelector("#privacy-confirm-important");

				important.hidden = cameraChanges.length === 0;
				showLines(important.querySelector("ul"), cameraChanges);
				showLines(
					dialog.querySelector("#privacy-confirm-changes"),
					changes.length === 0 && cameraChanges.length === 0
						? ["Es gibt keine Änderungen."]
						: changes,
				);
				dialog.showModal();
			});

			dialog.querySelector("[data-confirm-cancel]").addEventListener("click", () => {
				dialog.close();
			});
			dialog.querySelector("[data-confirm-yes]").addEventListener("click", () => {
				const field = document.createElement("input");

				field.type = "hidden";
				field.name = "confirm_privacy";
				field.value = "yes";
				form.append(field);
				form.dataset.confirmed = "yes";
				dialog.close();
				form.submit();
			});
		})();
	</script>

	<?php require __DIR__ . "/../src/components/job-watcher.php"; ?>
</body>
</html>
