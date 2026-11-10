<?php

declare(strict_types=1);

// The Verpixelung tab: its controls, the explanations (in words a child understands), and the
// conversion between the form and the config values. The limits here only shape the HTML inputs:
// src/settings.py, through the writer, takes its limits from the blur code and is the one validator.

require_once __DIR__ . "/settings-form.php";
require_once __DIR__ . "/preview-runner.php";

// A camera name as a per-camera KEY: no dot, because a dot separates the parts of a settings key.
const PRIVACY_CAMERA_KEY_PATTERN = '/^[A-Za-z0-9][A-Za-z0-9_-]*$/D';

// The box rows without a saved box that are always offered, so more can be added without JavaScript.
const PRIVACY_BLANK_BOX_ROWS = 3;

function privacyFieldId(string $key): string
{
	return "privacy-" . str_replace(".", "-", $key);
}

// The number controls shared by all blur cameras. "group" says in which fieldset one is shown.
function privacyFloatFields(): array
{
	return [
		[
			"key" => "privacy.blur.strength",
			"group" => "blur",
			"label" => "Wie grob sind die Kästchen?",
			"min" => "0.05",
			"max" => "0.5",
			"step" => "0.01",
			"help" => [
				"Das Bild wird zu einem Mosaik aus lauter Kästchen. Sind die Kästchen klein, sieht man noch viel davon. Sind sie groß, sieht man fast nichts mehr.",
				"Kleine Zahl = kleine Kästchen = weniger Schutz. Große Zahl = dicke Kästchen = mehr Schutz.",
			],
		],
		[
			"key" => "privacy.blur.padding_ratio",
			"group" => "blur",
			"label" => "Wie weit reicht der Schutz um einen Menschen herum?",
			"min" => "0.05",
			"max" => "1",
			"step" => "0.05",
			"help" => [
				"Um jeden Menschen kommt ein Mosaik-Mantel. Ist der Mantel eng, kann ein Arm oder ein Bein herausgucken. Ist er weit, ist alles gut bedeckt.",
				"Kleine Zahl = enger Mantel. Große Zahl = weiter Mantel = mehr Schutz.",
			],
		],
		[
			"key" => "privacy.blur.feather",
			"group" => "blur",
			"label" => "Wie weich ist der Rand vom Mosaik?",
			"min" => "0",
			"max" => "1",
			"step" => "0.05",
			"help" => [
				"Bei 0 hört das Mosaik mit einer harten Kante auf. Bei 1 wird es zum Rand hin immer durchsichtiger, wie ein weicher Pinselstrich.",
				"Der Mensch selbst ist immer ganz verpixelt. Das ändert nur, wie der Rand aussieht.",
			],
		],
		[
			"key" => "privacy.ignore_top_share",
			"group" => "top",
			"label" => "Wie viel vom oberen Bildrand wird ignoriert?",
			"min" => "0",
			"max" => "0.49",
			"step" => "0.01",
			"help" => [
				"Ganz oben im Bild sind meistens nur Himmel, Dächer oder die Halterung der Kamera. Wenn die Kamera dort einen Menschen zu sehen glaubt, ist das fast immer ein Irrtum.",
				"Die Zahl sagt, wie viel vom Bild von oben als Irrtums-Zone gilt: 0 = nichts, 0,33 = das obere Drittel. Der Höchstwert ist knapp unter 0,5, also die halbe Höhe.",
				"Achtung: Was dort erkannt wird, bleibt unverpixelt. Das gilt für alle Kameras.",
			],
		],
	];
}

// The control of one blur camera: how sure the camera must be that it sees a person.
function privacyScoreField(): array
{
	return [
		"label" => "Wie sicher muss die Kamera sein, dass da ein Mensch ist?",
		"min" => "0",
		"max" => "0.5",
		"step" => "0.01",
		"help" => [
			"Die Kamera gibt jedem Fund eine Sicherheit von 0 bis 1. Nur Funde über dieser Zahl werden verpixelt.",
			"0 = jeder Fund wird verpixelt. Das ist am sichersten, aber manchmal hält die Kamera auch Dinge für Menschen, die keine sind. Eine höhere Zahl lässt unsichere Funde in Ruhe: weniger falsche Kästchen, aber ein weit entfernter Mensch kann übersehen werden. Der Höchstwert ist 0,5.",
			"Unter 0,25 ändert sich nichts, so unsichere Funde meldet die Kamera gar nicht erst.",
		],
	];
}

function privacyBoxHelp(): array
{
	return [
		"Manchmal hält die Kamera einen Poller oder ein Boot für einen Menschen und verpixelt es. Mit einem Rahmen sagt man: Das hier ist kein Mensch.",
		"Ein Rahmen hat vier Zahlen, in Bildpunkten gemessen: links, oben, rechts, unten. Er gilt nur für Funde, die ungefähr so groß sind und an derselben Stelle liegen.",
		"Wo ein Rahmen liegt, wird nichts verpixelt, wenn ein Fund dazu passt. Darum Rahmen nur setzen, wenn dort sicher kein Mensch steht.",
	];
}

// Every camera the tab can show: the ones the settings page knows, plus the ones in the blur list.
function privacyKnownCameras(array $config): array
{
	$privacy = is_array($config["privacy"] ?? null) ? $config["privacy"] : [];
	$names = array_merge(settingsKnownCameras(), cameraNames($privacy["blur_cameras"] ?? []));
	$plain = array_filter(
		$names,
		static fn(string $name): bool => preg_match('/^[A-Za-z0-9][A-Za-z0-9._-]*$/D', $name) === 1,
	);
	$known = array_values(array_unique($plain));

	sort($known, SORT_NATURAL | SORT_FLAG_CASE);

	return $known;
}

function privacyNumberText(mixed $value): string
{
	return is_int($value) || is_float($value) || is_string($value) ? (string) $value : "";
}

// Boxes as the form shows them: rows of four texts. Anything that is not a box is left out.
function privacyBoxesForDisplay(mixed $boxes): array
{
	if (!is_array($boxes)) {
		return [];
	}

	$rows = [];

	foreach ($boxes as $box) {
		if (is_array($box) && count($box) === 4) {
			$rows[] = array_map(
				static fn(mixed $cell): string => is_scalar($cell) ? (string) $cell : "",
				array_values($box),
			);
		}
	}

	return $rows;
}

// Boxes of a config as whole numbers, for the restore button's data. Anything else is left out.
function privacyBoxesForDefaults(mixed $boxes): array
{
	if (!is_array($boxes)) {
		return [];
	}

	$rows = [];

	foreach ($boxes as $box) {
		if (is_array($box) && count($box) === 4 && count(array_filter($box, "is_int")) === 4) {
			$rows[] = array_values($box);
		}
	}

	return $rows;
}

// What the form shows, from a config: the number texts, the ticked blur cameras and one block (score
// and boxes) per blur camera whose name can be a settings key.
function privacyFormState(array $config): array
{
	$privacy = is_array($config["privacy"] ?? null) ? $config["privacy"] : [];
	$scores = is_array($privacy["min_person_score"] ?? null) ? $privacy["min_person_score"] : [];
	$boxes = is_array($privacy["ignore_boxes"] ?? null) ? $privacy["ignore_boxes"] : [];
	$floats = [];

	foreach (privacyFloatFields() as $field) {
		[$found, $value] = settingsLeaf($config, $field["key"]);
		$floats[$field["key"]] = $found ? privacyNumberText($value) : "";
	}

	$blurCameras = cameraNames($privacy["blur_cameras"] ?? []);
	$cameras = [];

	foreach ($blurCameras as $camera) {
		if (preg_match(PRIVACY_CAMERA_KEY_PATTERN, $camera) === 1) {
			$cameras[$camera] = [
				"score" => isset($scores[$camera]) ? privacyNumberText($scores[$camera]) : "0",
				"boxes" => privacyBoxesForDisplay($boxes[$camera] ?? []),
			];
		}
	}

	return ["blur_cameras" => $blurCameras, "floats" => $floats, "cameras" => $cameras];
}

// The same, from a submitted form: after a refusal the tab shows what was typed. Only ever displayed
// (escaped), never trusted.
function privacyFormStateFromPost(array $post): array
{
	$input = is_array($post["privacy"] ?? null) ? $post["privacy"] : [];
	$typed = is_array($input["floats"] ?? null) ? $input["floats"] : [];
	$scores = is_array($input["score"] ?? null) ? $input["score"] : [];
	$rows = is_array($input["boxes"] ?? null) ? $input["boxes"] : [];
	$floats = [];

	foreach (privacyFloatFields() as $field) {
		$value = $typed[$field["key"]] ?? "";
		$floats[$field["key"]] = is_string($value) ? $value : "";
	}

	$blurCameras = cameraNames($post["blur_cameras"] ?? []);
	$cameras = [];

	foreach ($blurCameras as $camera) {
		if (preg_match(PRIVACY_CAMERA_KEY_PATTERN, $camera) !== 1) {
			continue;
		}

		$score = $scores[$camera] ?? "0";
		$cameraRows = is_array($rows[$camera] ?? null) ? $rows[$camera] : [];
		$boxes = [];

		foreach ($cameraRows as $row) {
			$cells = [];

			foreach (["x0", "y0", "x1", "y1"] as $name) {
				$cell = is_array($row) ? ($row[$name] ?? "") : "";
				$cells[] = is_string($cell) ? trim($cell) : "";
			}

			if ($cells !== ["", "", "", ""]) {
				$boxes[] = $cells;
			}
		}

		$cameras[$camera] = ["score" => is_string($score) ? $score : "0", "boxes" => $boxes];
	}

	return ["blur_cameras" => $blurCameras, "floats" => $floats, "cameras" => $cameras];
}

// Text of a number field to a number; anything else stays text, so the writer's message names the
// problem. A decimal comma is accepted.
function privacyNumberValue(string $text): int|float|string
{
	$trimmed = trim($text);
	$dotted = str_replace(",", ".", $trimmed);

	if (strlen($dotted) > 12 || preg_match('/^[0-9]+(\.[0-9]+)?$/D', $dotted) !== 1) {
		return $trimmed;
	}

	return str_contains($dotted, ".") ? (float) $dotted : (int) $dotted;
}

// The boxes of one camera from its rows: blank rows are left out, a half-filled row goes on as text
// for the writer to refuse. Null when the rows are not rows at all.
function privacyBoxesFromRows(mixed $rows): ?array
{
	if (!is_array($rows) || count($rows) > 100) {
		return null;
	}

	$boxes = [];

	foreach ($rows as $row) {
		if (!is_array($row)) {
			return null;
		}

		$cells = [];

		foreach (["x0", "y0", "x1", "y1"] as $name) {
			$cell = $row[$name] ?? null;

			if (!is_string($cell)) {
				return null;
			}

			$cells[] = trim($cell);
		}

		if ($cells !== ["", "", "", ""]) {
			$boxes[] = array_map(settingsInputValue(...), $cells);
		}
	}

	return $boxes;
}

// [values, problems]: the nested values the writer validates, or the reasons nothing is sent. Only
// the form's fixed fields and the known cameras are read: nothing else ever gets through.
function privacyValuesFromPost(array $post, array $knownCameras): array
{
	$input = $post["privacy"] ?? null;

	if (!is_array($input) || !is_array($input["floats"] ?? null)) {
		return [[], [SETTINGS_FORM_INCOMPLETE]];
	}

	$values = [];

	foreach (privacyFloatFields() as $field) {
		$text = $input["floats"][$field["key"]] ?? null;

		if (!is_string($text)) {
			return [[], [SETTINGS_FORM_INCOMPLETE]];
		}

		setSettingsLeaf($values, $field["key"], privacyNumberValue($text));
	}

	// An unticked box is not sent at all, so a missing list means no camera is ticked.
	$blurCameras = settingsCheckedCameras($post["blur_cameras"] ?? [], $knownCameras);

	if ($blurCameras === null) {
		return [[], ["Die ausgewählte Kamera ist ungültig."]];
	}

	setSettingsLeaf($values, "privacy.blur_cameras", $blurCameras);

	$scores = is_array($input["score"] ?? null) ? $input["score"] : [];
	$rows = is_array($input["boxes"] ?? null) ? $input["boxes"] : [];

	foreach (array_unique([...array_keys($scores), ...array_keys($rows)]) as $key) {
		$camera = (string) $key;

		if (!in_array($camera, $knownCameras, true) || preg_match(PRIVACY_CAMERA_KEY_PATTERN, $camera) !== 1) {
			return [[], ["Die ausgewählte Kamera ist ungültig."]];
		}

		if (array_key_exists($key, $scores)) {
			if (!is_string($scores[$key])) {
				return [[], [SETTINGS_FORM_INCOMPLETE]];
			}

			setSettingsLeaf($values, "privacy.min_person_score." . $camera, privacyNumberValue($scores[$key]));
		}

		if (array_key_exists($key, $rows)) {
			$boxes = privacyBoxesFromRows($rows[$key]);

			if ($boxes === null) {
				return [[], [SETTINGS_FORM_INCOMPLETE]];
			}

			setSettingsLeaf($values, "privacy.ignore_boxes." . $camera, $boxes);
		}
	}

	return [$values, []];
}

// The element a writer message points at: the control of that key.
function privacyErrorTarget(string $key): string
{
	if (str_starts_with($key, "privacy.min_person_score.")) {
		return "privacy-score-" . substr($key, strlen("privacy.min_person_score."));
	}

	if (str_starts_with($key, "privacy.ignore_boxes.")) {
		return "privacy-boxes-" . substr($key, strlen("privacy.ignore_boxes."));
	}

	return $key === "privacy.blur_cameras" ? "privacy-blur-cameras" : privacyFieldId($key);
}

// What a message names in the summary: the label of the control, or the camera and what it is about.
function privacyErrorLabel(string $key): string
{
	foreach (privacyFloatFields() as $field) {
		if ($field["key"] === $key) {
			return $field["label"];
		}
	}

	if (str_starts_with($key, "privacy.min_person_score.")) {
		return "Kamera " . substr($key, strlen("privacy.min_person_score.")) . ": Sicherheit";
	}

	if (str_starts_with($key, "privacy.ignore_boxes.")) {
		return "Kamera " . substr($key, strlen("privacy.ignore_boxes.")) . ": Rahmen";
	}

	return "Verpixelte Kameras";
}

// The writer's messages start with the key ("privacy.blur.strength: ..."). Returns [messages by key,
// the others]: the first are shown next to their control, all of them in the summary.
function privacySplitErrors(array $errors): array
{
	$byKey = [];
	$general = [];

	foreach ($errors as $error) {
		$parts = explode(": ", (string) $error, 2);

		if (count($parts) === 2 && str_starts_with($parts[0], "privacy.")) {
			$byKey[$parts[0]] ??= $parts[1];
		} else {
			$general[] = (string) $error;
		}
	}

	return [$byKey, $general];
}

function renderPrivacyHelp(string $id, array $paragraphs): void
{
	?>
	<div class="privacy-help" id="<?= settingsHtml($id) ?>-help">
		<?php foreach ($paragraphs as $paragraph): ?>
			<p><?= settingsHtml($paragraph) ?></p>
		<?php endforeach; ?>
	</div>
	<?php
}

// One number control: the number field is the real one (it is what is sent and what the keyboard and
// screen readers use); the slider next to it only helps the mouse and is shown by the script.
function renderPrivacyNumber(
	string $id,
	string $name,
	array $field,
	string $value,
	?string $default,
	?string $error,
): void {
	$describedBy = $id . "-help" . ($error !== null ? " " . $id . "-error" : "");

	?>
	<div class="settings-field privacy-slider">
		<label for="<?= settingsHtml($id) ?>"><?= settingsHtml($field["label"]) ?></label>
		<div class="privacy-slider-row">
			<input
				type="range"
				class="privacy-range"
				data-slider-for="<?= settingsHtml($id) ?>"
				min="<?= settingsHtml($field["min"]) ?>"
				max="<?= settingsHtml($field["max"]) ?>"
				step="<?= settingsHtml($field["step"]) ?>"
				value="<?= settingsHtml($value) ?>"
				aria-hidden="true"
				tabindex="-1"
				hidden
			>
			<input
				type="number"
				id="<?= settingsHtml($id) ?>"
				name="<?= settingsHtml($name) ?>"
				value="<?= settingsHtml($value) ?>"
				<?= $default !== null ? 'data-default="' . settingsHtml($default) . '"' : "" ?>
				min="<?= settingsHtml($field["min"]) ?>"
				max="<?= settingsHtml($field["max"]) ?>"
				step="any"
				inputmode="decimal"
				required
				<?= $error !== null ? 'aria-invalid="true"' : "" ?>
				aria-describedby="<?= settingsHtml($describedBy) ?>"
			>
		</div>
		<?php if ($default !== null): ?>
			<span class="settings-default">Standard: <?= settingsHtml($default) ?></span>
		<?php endif; ?>
		<?php renderPrivacyHelp($id, $field["help"]); ?>
		<?php if ($error !== null): ?>
			<p class="field-error" id="<?= settingsHtml($id) ?>-error"><?= settingsHtml($error) ?></p>
		<?php endif; ?>
	</div>
	<?php
}

// The blur camera list. A camera that already blurs (config.json) is marked, so nobody takes its
// tick away by accident.
function renderPrivacyCameraBoxes(array $knownCameras, array $ticked, array $baseList): void
{
	?>
	<div class="settings-cameras" id="privacy-blur-cameras">
		<?php foreach ($knownCameras as $camera): ?>
			<?php $live = in_array($camera, $baseList, true); ?>
			<label>
				<input
					type="checkbox"
					data-default-checked="<?= $live ? "1" : "0" ?>"
					<?= $live ? 'data-live="1"' : "" ?>
					name="blur_cameras[]"
					value="<?= settingsHtml($camera) ?>"
					<?= in_array($camera, $ticked, true) ? "checked" : "" ?>
				>
				<?= settingsHtml($camera) ?>
				<?php if ($live): ?>
					<span class="privacy-live">läuft schon</span>
				<?php endif; ?>
			</label>
		<?php endforeach; ?>
	</div>
	<?php
}

// One row of four box numbers. $index and $number are placeholders in the template the script clones.
function renderPrivacyBoxRow(string $camera, string $index, string $number, array $cells): void
{
	$names = ["x0" => "links", "y0" => "oben", "x1" => "rechts", "y1" => "unten"];
	$position = 0;

	?>
	<div class="privacy-box-row">
		<span class="privacy-box-number" aria-hidden="true"><?= settingsHtml($number) ?></span>
		<?php foreach ($names as $name => $word): ?>
			<label>
				<span><?= settingsHtml($word) ?></span>
				<input
					type="number"
					name="privacy[boxes][<?= settingsHtml($camera) ?>][<?= settingsHtml($index) ?>][<?= $name ?>]"
					value="<?= settingsHtml($cells[$position++] ?? "") ?>"
					min="0"
					max="20000"
					step="1"
					inputmode="numeric"
					aria-label="Kamera <?= settingsHtml($camera) ?>, Rahmen <?= settingsHtml($number) ?>, <?= settingsHtml($word) ?>"
				>
			</label>
		<?php endforeach; ?>
		<button type="button" class="privacy-box-remove settings-default-button" data-remove-box hidden>Entfernen</button>
	</div>
	<?php
}

// The ignore boxes of one camera: the saved rows, blank rows to add more, and the template and
// button the script uses to add rows. $defaultBoxes is what the restore button sets back.
function renderPrivacyBoxes(string $camera, array $boxes, array $defaultBoxes, ?string $error): void
{
	$id = "privacy-boxes-" . $camera;
	$describedBy = $id . "-help" . ($error !== null ? " " . $id . "-error" : "");
	$rowCount = count($boxes) + PRIVACY_BLANK_BOX_ROWS;

	?>
	<div class="settings-field privacy-boxes-field">
		<h3 class="privacy-boxes-title">Stellen, die nie verpixelt werden (Rahmen)</h3>
		<?php renderPrivacyHelp($id, privacyBoxHelp()); ?>
		<div
			class="privacy-boxes"
			id="<?= settingsHtml($id) ?>"
			data-camera="<?= settingsHtml($camera) ?>"
			data-label="Rahmen von <?= settingsHtml($camera) ?>"
			data-default-boxes="<?= settingsHtml((string) json_encode($defaultBoxes)) ?>"
			data-next-index="<?= (int) $rowCount ?>"
			role="group"
			aria-describedby="<?= settingsHtml($describedBy) ?>"
		>
			<?php for ($index = 0; $index < $rowCount; $index++): ?>
				<?php renderPrivacyBoxRow($camera, (string) $index, (string) ($index + 1), $boxes[$index] ?? []); ?>
			<?php endfor; ?>
		</div>
		<template data-box-template>
			<?php renderPrivacyBoxRow($camera, "__INDEX__", "__NUMBER__", []); ?>
		</template>
		<button type="button" class="settings-default-button" data-add-box hidden>Rahmen hinzufügen</button>
		<?php if ($error !== null): ?>
			<p class="field-error" id="<?= settingsHtml($id) ?>-error"><?= settingsHtml($error) ?></p>
		<?php endif; ?>
	</div>
	<?php
}

// The text under a preview picture; the script builds the same sentence for a picture it loads.
function privacyPreviewCaption(array $info): string
{
	return "Aufgenommen am " . $info["takenText"] . " Uhr. Bildgröße: "
		. $info["width"] . " × " . $info["height"] . " Punkte.";
}

// The picture of one blur camera, so the ignore boxes can be placed by eye. $info is what
// readPreviewInfo() found (null: no picture yet). The button is shown by the script and sends
// nothing with the form: it asks preview-refresh.php for a fresh picture and shows it.
function renderPrivacyPreview(string $camera, ?array $info): void
{
	$id = "privacy-preview-" . $camera;

	?>
	<section
		class="privacy-preview"
		data-preview-camera="<?= settingsHtml($camera) ?>"
		<?= $info !== null ? 'data-preview-width="' . (int) $info["width"] . '" data-preview-height="' . (int) $info["height"] . '"' : "" ?>
		aria-labelledby="<?= settingsHtml($id) ?>-title"
	>
		<h3 class="privacy-boxes-title" id="<?= settingsHtml($id) ?>-title">Bild der Kamera</h3>
		<div class="privacy-help">
			<p>Das ist ein echtes Bild von dieser Kamera. Die Verpixelung hat es schon angeschaut. Menschen darauf sind unkenntlich gemacht.</p>
			<p>Das Bild zeigt dir, wo ein Rahmen liegen soll. Die Zahlen eines Rahmens sind Punkte im Bild: von links nach rechts und von oben nach unten.</p>
		</div>
		<?php if ($info !== null): ?>
			<figure class="privacy-preview-figure">
				<div class="privacy-preview-stage">
					<img
						src="<?= settingsHtml(previewUrl($camera, $info["version"])) ?>"
						width="<?= (int) $info["width"] ?>"
						height="<?= (int) $info["height"] ?>"
						alt="<?= settingsHtml("Vorschaubild der Kamera " . $camera . " vom " . $info["takenText"] . " Uhr") ?>"
					>
				</div>
				<figcaption><?= settingsHtml(privacyPreviewCaption($info)) ?></figcaption>
			</figure>
		<?php else: ?>
			<p class="privacy-preview-empty">Für diese Kamera gibt es noch kein Bild. Es entsteht, sobald die Verpixelung in der Nacht Bilder dieser Kamera geprüft hat.</p>
		<?php endif; ?>
		<div class="privacy-help" data-draw-help hidden>
			<p>So malst du einen Rahmen: Drücke „Rahmen zeichnen“. Dann ziehst du mit der Maus oder dem Finger ein Rechteck über die Stelle, die kein Mensch ist. Die Zahlen unten füllen sich von selbst. Du kannst die Zahlen auch selbst eintippen.</p>
			<p>Türkise Rechtecke sind Rahmen, die es schon gibt. Der rote Streifen oben ist der obere Bildrand, der ignoriert wird. Soll ein Rahmen weg? Dann drücke unten in seiner Zeile auf „Entfernen“.</p>
		</div>
		<p class="privacy-preview-actions">
			<button type="button" class="settings-reset" data-preview-draw aria-pressed="false" hidden>Rahmen zeichnen</button>
			<button type="button" class="settings-reset" data-preview-refresh hidden>Vorschau aktualisieren</button>
			<span class="settings-hint" role="status" data-preview-status></span>
		</p>
	</section>
	<?php
}
