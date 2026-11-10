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
					<?php renderPrivacyPreview((string) $camera, readPreviewInfo((string) $camera)); ?>
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
					const container = remove.closest(".privacy-boxes");

					remove.closest(".privacy-box-row").remove();
					refreshContainer(container);
				}
			});
			form.querySelectorAll("[data-add-box]").forEach((button) => {
				button.hidden = false;
				button.addEventListener("click", () => {
					const container = button.closest("fieldset").querySelector(".privacy-boxes");

					addBoxRow(container);
					refreshContainer(container);
				});
			});

			// The drawing editor on the picture. A layer of plain boxes lies over the picture, placed in
			// percent of the picture's own size, so it scales with the picture and a position on it is the
			// box number by one scale factor. The rows of four numbers stay the real control (and the way
			// to work without a mouse): the layer only shows them and adds rows from a drag.
			const topShare = form.querySelector("#privacy-privacy-ignore_top_share");
			const topRange = form.querySelector(`[data-slider-for="${topShare.id}"]`);

			// The field's own limit: the strip cannot be pulled further than the page would accept.
			const TOP_SHARE_MAX = Number(topShare.max);

			// The strip counts only while the field holds a usable number.
			const currentShare = () => {
				const value = Number(topShare.value);

				return topShare.value.trim() !== "" && value > 0 && value < 0.5 ? value : 0;
			};

			// The top share is ONE value for every camera: a drag on any picture writes the same field and
			// slider, and every picture follows.
			const setTopShare = (value) => {
				topShare.value = String(value);
				topRange.value = String(value);
				refreshAll();
			};

			// Smaller than this (in screen pixels) is a click or a slip of the hand, not a box.
			const MIN_DRAWN_SIDE = 6;

			const sectionOf = (container) => container.closest("fieldset").querySelector("[data-preview-camera]");
			const containerOf = (section) => section.closest("fieldset").querySelector(".privacy-boxes");
			const percent = (part, whole) => `${(part / whole) * 100}%`;

			const pictureSize = (section) => {
				const width = Number(section.dataset.previewWidth);
				const height = Number(section.dataset.previewHeight);

				return width > 0 && height > 0 ? { width, height } : null;
			};

			// A row as a box, or null while it is blank or not a usable box yet.
			const boxOfRow = (row) => {
				const inputs = Array.from(row.querySelectorAll("input"));

				if (inputs.some((input) => input.value.trim() === "")) {
					return null;
				}

				const [x0, y0, x1, y1] = inputs.map((input) => Number(input.value));

				return [x0, y0, x1, y1].every(Number.isFinite) && x1 > x0 && y1 > y0 ? { x0, y0, x1, y1 } : null;
			};

			// The rows count 1, 2, 3 ... in the order they stand, also after one was removed or added: a
			// rectangle on the picture carries the same number.
			const numberRows = (container) => {
				container.querySelectorAll(".privacy-box-row").forEach((row, index) => {
					const number = String(index + 1);

					row.querySelector(".privacy-box-number").textContent = number;
					row.querySelectorAll("input").forEach((input) => {
						input.setAttribute("aria-label", input.getAttribute("aria-label").replace(/Rahmen \d+/, `Rahmen ${number}`));
					});
				});
			};

			const badge = (text) => {
				const label = document.createElement("span");

				label.textContent = text;

				return label;
			};

			// Everything on the layer comes from the fields: the band from the top-share field, one
			// rectangle per usable row. The row that has the focus is marked on the picture.
			const redrawSection = (section) => {
				const size = pictureSize(section);
				const layer = layerOf(section);

				if (layer === null || size === null) {
					return;
				}

				const rows = Array.from(containerOf(section).querySelectorAll(".privacy-box-row"));
				const focused = rows.find((row) => row.contains(document.activeElement));
				const share = topShare.value.trim() === "" ? 0 : Number(topShare.value);
				const shapes = [];

				if (share > 0 && share < 0.5) {
					const band = document.createElement("div");

					band.className = "privacy-top-band";
					band.style.height = `${share * 100}%`;
					band.append(badge("Oben: wird ignoriert"));
					shapes.push(band);
				}

				rows.forEach((row, index) => {
					const box = boxOfRow(row);

					if (box === null) {
						return;
					}

					const shape = document.createElement("div");

					shape.className = row === focused ? "privacy-box-shape is-active" : "privacy-box-shape";
					shape.style.left = percent(box.x0, size.width);
					shape.style.top = percent(box.y0, size.height);
					shape.style.width = percent(box.x1 - box.x0, size.width);
					shape.style.height = percent(box.y1 - box.y0, size.height);
					shape.dataset.row = String(index);
					shape.append(badge(String(index + 1)));
					shapes.push(shape);
				});

				// The handle on the strip's lower edge, on top of everything. At 0 it waits at the top, so the
				// strip can be pulled out of nothing. It shows only while editing is on (see the CSS).
				const handle = document.createElement("div");

				handle.className = "privacy-top-handle";
				handle.style.top = `max(8px, ${currentShare() * 100}%)`;
				handle.append(badge("Oberer Rand: gilt für alle Kameras"));
				shapes.push(handle);

				layer.replaceChildren(...shapes);
			};

			const refreshContainer = (container) => {
				numberRows(container);
				// The note under the heading is there exactly while no row is.
				container.closest(".privacy-boxes-field").querySelector(".privacy-boxes-empty").hidden =
					container.querySelector(".privacy-box-row") !== null;
				redrawSection(sectionOf(container));
			};

			const refreshAll = () => {
				form.querySelectorAll(".privacy-boxes").forEach(refreshContainer);
			};

			// A drawn rectangle becomes a row: the first blank one, or a new one.
			const placeBox = (container, cells) => {
				const rows = Array.from(container.querySelectorAll(".privacy-box-row"));
				let row = rows.find((candidate) =>
					Array.from(candidate.querySelectorAll("input")).every((input) => input.value.trim() === ""),
				);

				if (row === undefined) {
					addBoxRow(container, cells.map(String));
					row = container.lastElementChild;
				} else {
					row.querySelectorAll("input").forEach((input, position) => {
						input.value = String(cells[position]);
					});
				}

				refreshContainer(container);

				return Array.from(container.querySelectorAll(".privacy-box-row")).indexOf(row) + 1;
			};

			// The gestures on the layer. They only run while editing is on (class is-drawing); off, the layer
			// lets every touch and click through, so the picture never blocks scrolling. A drag that starts on
			// a box moves that box, a drag that starts anywhere else draws a new one.
			const enableDrawing = (section, layer) => {
				const status = section.querySelector("[data-preview-status]");
				let gesture = null;

				const pointAt = (event) => {
					const bounds = layer.getBoundingClientRect();

					return {
						x: Math.min(Math.max(event.clientX - bounds.left, 0), bounds.width),
						y: Math.min(Math.max(event.clientY - bounds.top, 0), bounds.height),
						width: bounds.width,
						height: bounds.height,
					};
				};

				const stop = () => {
					gesture?.draft?.remove();
					gesture = null;
				};

				// The box at its new place: moved by the drag, exactly as big as before, inside the picture.
				const movedBox = (box, now, size) => {
					const width = box.x1 - box.x0;
					const height = box.y1 - box.y0;
					const x0 = Math.round(box.x0 + ((now.x - gesture.start.x) * size.width) / now.width);
					const y0 = Math.round(box.y0 + ((now.y - gesture.start.y) * size.height) / now.height);
					const left = Math.min(Math.max(x0, 0), Math.max(size.width - width, 0));
					const top = Math.min(Math.max(y0, 0), Math.max(size.height - height, 0));

					return { x0: left, y0: top, x1: left + width, y1: top + height };
				};

				layer.addEventListener("pointerdown", (event) => {
					if (!layer.classList.contains("is-drawing") || event.button !== 0) {
						return;
					}

					event.preventDefault();
					layer.setPointerCapture(event.pointerId);

					const start = pointAt(event);

					// The strip's edge: the drag changes the global top share, not a box.
					if (event.target.closest(".privacy-top-handle") !== null) {
						gesture = { kind: "strip", start, share: currentShare(), moved: false };

						return;
					}

					const grabbed = event.target.closest(".privacy-box-shape[data-row]");
					const row = grabbed === null
						? undefined
						: containerOf(section).querySelectorAll(".privacy-box-row")[Number(grabbed.dataset.row)];
					const box = row === undefined ? null : boxOfRow(row);

					if (box !== null) {
						grabbed.classList.add("is-active");
						gesture = { kind: "move", start, box, row, shape: grabbed };

						return;
					}

					const draft = document.createElement("div");

					draft.className = "privacy-box-shape is-draft";
					layer.append(draft);
					gesture = { kind: "draw", start, draft };
				});

				layer.addEventListener("pointermove", (event) => {
					if (gesture === null) {
						return;
					}

					const now = pointAt(event);
					const size = pictureSize(section);

					// The pointer's way down the picture, as a share of its height, from where the edge was.
					if (gesture.kind === "strip") {
						const share = gesture.share + (now.y - gesture.start.y) / now.height;

						gesture.moved = true;
						setTopShare(Math.min(Math.max(Math.round(share * 100) / 100, 0), TOP_SHARE_MAX));

						return;
					}

					// The box follows the pointer on the picture; the row's numbers change when it is let go.
					if (gesture.kind === "move") {
						const to = movedBox(gesture.box, now, size);

						gesture.shape.style.left = percent(to.x0, size.width);
						gesture.shape.style.top = percent(to.y0, size.height);

						return;
					}

					const { start, draft } = gesture;

					draft.style.left = percent(Math.min(start.x, now.x), now.width);
					draft.style.top = percent(Math.min(start.y, now.y), now.height);
					draft.style.width = percent(Math.abs(now.x - start.x), now.width);
					draft.style.height = percent(Math.abs(now.y - start.y), now.height);
				});

				layer.addEventListener("pointerup", (event) => {
					if (gesture === null) {
						return;
					}

					const { kind, start, box, row } = gesture;

					if (kind === "strip") {
						const moved = gesture.moved;

						stop();

						if (moved) {
							status.textContent = `Oberer Rand: ${currentShare().toLocaleString("de-DE")} der Bildhöhe, für alle Kameras. Zum Übernehmen unten auf „Speichern“ drücken.`;
						}

						refreshAll();

						return;
					}

					const end = pointAt(event);
					const size = pictureSize(section);
					const container = containerOf(section);

					if (kind === "move" && size !== null) {
						const to = movedBox(box, end, size);

						stop();

						// A click on a box, or a slip that moves it by less than a picture pixel, changes nothing.
						if (to.x0 !== box.x0 || to.y0 !== box.y0) {
							const cells = [to.x0, to.y0, to.x1, to.y1];

							row.querySelectorAll("input").forEach((input, position) => {
								input.value = String(cells[position]);
							});

							const number = Array.from(container.querySelectorAll(".privacy-box-row")).indexOf(row) + 1;

							status.textContent = `Rahmen ${number} wurde verschoben. Zum Übernehmen unten auf „Speichern“ drücken.`;
						}

						refreshContainer(container);

						return;
					}

					const left = Math.min(start.x, end.x);
					const right = Math.max(start.x, end.x);
					const top = Math.min(start.y, end.y);
					const bottom = Math.max(start.y, end.y);

					stop();

					if (size === null || right - left < MIN_DRAWN_SIDE || bottom - top < MIN_DRAWN_SIDE) {
						redrawSection(section);

						return;
					}

					// Screen pixels to picture pixels: one factor per direction.
					const scaleX = size.width / end.width;
					const scaleY = size.height / end.height;
					const cells = [left * scaleX, top * scaleY, right * scaleX, bottom * scaleY].map(Math.round);

					if (cells[2] <= cells[0] || cells[3] <= cells[1]) {
						redrawSection(section);

						return;
					}

					const number = placeBox(container, cells);

					status.textContent = `Rahmen ${number} ist dazugekommen. Zum Übernehmen unten auf „Speichern“ drücken.`;
				});

				layer.addEventListener("pointercancel", () => {
					// A cancelled drag of the strip leaves the value as it was before the drag.
					if (gesture?.kind === "strip") {
						setTopShare(gesture.share);
					}

					stop();
					redrawSection(section);
				});
			};

			// The layer is made when the picture is there, and only once.
			const layerOf = (section) => {
				const stage = section.querySelector(".privacy-preview-stage");

				if (stage === null) {
					return null;
				}

				let layer = stage.querySelector(".privacy-preview-layer");

				if (layer === null) {
					layer = document.createElement("div");
					layer.className = "privacy-preview-layer";
					// Decoration for the mouse: the rows are the control that works for everyone.
					layer.setAttribute("aria-hidden", "true");
					stage.append(layer);
					enableDrawing(section, layer);
				}

				return layer;
			};

			// Shows the drawing tools for a camera that has a picture, and hides them for one without.
			const prepareSection = (section) => {
				const hasPicture = section.querySelector(".privacy-preview-stage") !== null;

				section.querySelector("[data-preview-draw]").hidden = !hasPicture;
				section.querySelector("[data-draw-help]").hidden = !hasPicture;

				if (hasPicture) {
					refreshContainer(containerOf(section));
				}
			};

			form.querySelectorAll("[data-preview-draw]").forEach((button) => {
				const section = button.closest("[data-preview-camera]");
				const status = section.querySelector("[data-preview-status]");

				button.addEventListener("click", () => {
					const layer = layerOf(section);

					if (layer === null) {
						return;
					}

					const drawing = button.getAttribute("aria-pressed") !== "true";

					button.setAttribute("aria-pressed", String(drawing));
					layer.classList.toggle("is-drawing", drawing);
					status.textContent = drawing
						? "Bearbeiten ist an. Ziehe ein Rechteck über das Bild oder schiebe einen Rahmen."
						: "Bearbeiten ist aus.";
				});
			});

			// The picture follows the fields while they are typed in, and the focused row lights up.
			form.addEventListener("input", (event) => {
				const container = event.target.closest(".privacy-boxes");

				// The slider moves the number field without an event of its own.
				if (event.target === topShare || event.target.dataset.sliderFor === topShare.id) {
					refreshAll();
				} else if (container !== null) {
					refreshContainer(container);
				}
			});
			form.addEventListener("focusin", (event) => {
				const container = event.target.closest(".privacy-boxes");

				if (container !== null) {
					refreshContainer(container);
				}
			});
			form.addEventListener("focusout", (event) => {
				const container = event.target.closest(".privacy-boxes");

				// The focus is still on the old field while the event runs.
				if (container !== null) {
					setTimeout(() => refreshContainer(container), 0);
				}
			});

			// The picture of a camera, from what the server answered. Built with the DOM and filled with
			// textContent: the answer is shown as text, never as markup.
			const showPicture = (section, picture) => {
				let figure = section.querySelector("figure");

				if (figure === null) {
					const stage = document.createElement("div");

					stage.className = "privacy-preview-stage";
					stage.append(document.createElement("img"));
					figure = document.createElement("figure");
					figure.className = "privacy-preview-figure";
					figure.append(stage, document.createElement("figcaption"));
					section.querySelector(".privacy-preview-empty")?.remove();
					section.querySelector(".privacy-help").after(figure);
				}

				const image = figure.querySelector("img");

				image.src = picture.url;
				image.width = picture.width;
				image.height = picture.height;
				image.alt = `Vorschaubild der Kamera ${section.dataset.previewCamera} vom ${picture.takenText} Uhr`;
				figure.querySelector("figcaption").textContent =
					`Aufgenommen am ${picture.takenText} Uhr. Bildgröße: ${picture.width} × ${picture.height} Punkte.`;

				// The layer lies over the picture: its size is what the boxes are measured against.
				section.dataset.previewWidth = String(picture.width);
				section.dataset.previewHeight = String(picture.height);
				prepareSection(section);
			};

			form.querySelectorAll("[data-preview-camera]").forEach(prepareSection);
			refreshAll();

			// "Vorschau aktualisieren": the form's own token goes along, and nothing of the form's
			// values: the button saves nothing and the unsaved changes stay as they are. Without
			// JavaScript the button stays hidden, because it would do nothing.
			const token = form.querySelector('input[name="csrf_token"]').value;

			form.querySelectorAll("[data-preview-refresh]").forEach((button) => {
				const section = button.closest("[data-preview-camera]");
				const status = section.querySelector("[data-preview-status]");

				button.hidden = false;
				button.addEventListener("click", async () => {
					button.disabled = true;
					status.textContent = "Das Bild wird geholt. Das dauert einen Moment …";

					try {
						const response = await fetch("/preview-refresh.php", {
							method: "POST",
							headers: { Accept: "application/json" },
							body: new URLSearchParams({
								csrf_token: token,
								camera: section.dataset.previewCamera,
							}),
						});
						const reply = await response.json();

						if (reply.status === "ok") {
							showPicture(section, reply.picture);
						}

						status.textContent = reply.message;
					} catch {
						status.textContent = "Das Bild konnte nicht geholt werden. Bitte später noch einmal versuchen.";
					} finally {
						button.disabled = false;
					}
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
				});

				note.textContent = `${what}: Standardwerte eingetragen. Zum Übernehmen bitte speichern.`;
				note.hidden = false;
				// The rows and the top-share field changed without an event the picture listens to.
				refreshAll();
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
				// The event runs before the browser puts the values back.
				setTimeout(refreshAll, 0);
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
