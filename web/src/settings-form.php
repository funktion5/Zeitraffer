<?php

declare(strict_types=1);

// The fields of the settings page and the conversion between the form and the config values. The
// ranges only shape the HTML inputs: src/settings.py, through the writer, is the one validator.

const SETTINGS_FORM_INCOMPLETE = "Das Formular war unvollständig. Bitte die Seite neu laden.";

const SETTINGS_MONTH_NAMES = [
	1 => "Januar",
	2 => "Februar",
	3 => "März",
	4 => "April",
	5 => "Mai",
	6 => "Juni",
	7 => "Juli",
	8 => "August",
	9 => "September",
	10 => "Oktober",
	11 => "November",
	12 => "Dezember",
];

// Address of a file in web/public with its mtime as the version, so a browser never keeps an old
// script.
function assetUrl(string $name): string
{
	$modified = filemtime(dirname(__DIR__) . "/public/" . $name);

	return "/" . $name . "?v=" . ($modified === false ? 0 : $modified);
}

function settingsHtml(string $text): string
{
	return htmlspecialchars($text, ENT_QUOTES, "UTF-8");
}

function settingsFieldId(string $key): string
{
	return "setting-" . str_replace(".", "-", $key);
}

// "HH:MM" as minutes since midnight: what a time slider counts in.
function settingsClockMinutes(string $time): int
{
	[$hours, $minutes] = array_map("intval", explode(":", $time));

	return $hours * 60 + $minutes;
}

// A bound of a field as its slider counts it: a time slider in minutes since midnight, a number
// slider in the number itself.
function settingsSliderBound(array $field, string|int $bound): int
{
	return $field["type"] === "time" ? settingsClockMinutes((string) $bound) : (int) $bound;
}

// Every one-value field of the page, in page order. "group" says in which fieldset it is shown.
function settingsScalarFields(): array
{
	$fields = [
		[
			"key" => "timelapse.crf",
			"group" => "quality",
			"label" => "Qualität (CRF)",
			"type" => "number",
			"min" => 18,
			"max" => 35,
			"hint" => "Niedrigere Zahl = schärferes Bild, aber größere Datei. Gilt nur für Videos, die danach gebaut werden.",
		],
		[
			"key" => "timelapse.daily_framerate",
			"group" => "quality",
			"label" => "Bilder pro Sekunde, Tagesvideo",
			"type" => "number",
			"min" => 1,
			"max" => 60,
		],
		[
			"key" => "timelapse.monthly_framerate",
			"group" => "quality",
			"label" => "Bilder pro Sekunde, Monatsvideo",
			"type" => "number",
			"min" => 1,
			"max" => 60,
		],
		[
			"key" => "timelapse.yearly_framerate",
			"group" => "quality",
			"label" => "Bilder pro Sekunde, Jahresvideo",
			"type" => "number",
			"min" => 1,
			"max" => 60,
		],
		[
			"key" => "flagger.retention_days",
			"group" => "flagger",
			"label" => "Highlights aufbewahren (Tage)",
			"type" => "number",
			"min" => 7,
			"max" => 365,
		],
		[
			"key" => "daylight_buffer_minutes",
			"group" => "daylight",
			"label" => "Tageslicht-Puffer bei manuellen Videos (Minuten)",
			"type" => "number",
			"min" => 0,
			"max" => 240,
		],
		[
			"key" => "interval_window.target_time",
			"group" => "daylight",
			"label" => "Mittagsbild: Zielzeit",
			"type" => "time",
			"min" => "10:00",
			"max" => "14:00",
			"slider_step" => 15,
			"hint" => "Nur Zeiten bei Tageslicht: 10:00 bis 14:00 Uhr.",
		],
		[
			"key" => "interval_window.tolerance_minutes",
			"group" => "daylight",
			"label" => "Mittagsbild: Abweichung (± Minuten)",
			"type" => "number",
			"min" => 1,
			"max" => 120,
		],
		[
			"key" => "min_coverage_days.monthly",
			"group" => "daylight",
			"label" => "Monatsvideo: mindestens so viele Tage mit Bildern",
			"type" => "number",
			"min" => 1,
			"max" => 30,
			"slider_step" => 1,
		],
		[
			"key" => "min_coverage_days.yearly",
			"group" => "daylight",
			"label" => "Jahresvideo: mindestens so viele Tage mit Bildern",
			"type" => "number",
			"min" => 1,
			"max" => 365,
			"slider_step" => 1,
		],
		[
			"key" => "log_retention_days",
			"group" => "logs",
			"label" => "Protokolle aufbewahren (Tage)",
			"type" => "number",
			"min" => 1,
			"max" => 365,
		],
	];

	foreach (SETTINGS_MONTH_NAMES as $month => $name) {
		$fields[] = [
			"key" => "automatic_daylight_buffer_minutes.$month",
			"group" => "months",
			"label" => $name,
			"type" => "number",
			"min" => 0,
			"max" => 240,
		];
	}

	return $fields;
}

// Every camera the page can show: the cameras the night run lists, plus the ones already ignored
// (the list file leaves those out). Plain names only: a name ends up in file paths.
function settingsKnownCameras(): array
{
	$names = array_merge(findAvailableCameras(), getIgnoredCameras());
	$plain = array_filter(
		$names,
		static fn($name): bool => is_string($name)
			&& preg_match('/^[A-Za-z0-9][A-Za-z0-9._-]*$/D', $name) === 1,
	);
	$known = array_values(array_unique($plain));

	sort($known, SORT_NATURAL | SORT_FLAG_CASE);

	return $known;
}

// What the form shows, from a config: [dotted key => text], the ticked cameras, the ticked flagger
// cameras.
function settingsFormState(array $config, array $knownCameras): array
{
	$fields = [];

	foreach (settingsScalarFields() as $field) {
		[$found, $value] = settingsLeaf($config, $field["key"]);
		$fields[$field["key"]] = $found && (is_int($value) || is_string($value)) ? (string) $value : "";
	}

	$flaggerConfig = $config["flagger"] ?? [];

	return [
		"fields" => $fields,
		"processed" => array_values(array_diff($knownCameras, cameraNames($config["ignored_cameras"] ?? []))),
		"flagger" => cameraNames(is_array($flaggerConfig) ? ($flaggerConfig["cameras"] ?? []) : []),
	];
}

// The same, from a submitted form: after a refused save the page shows what was typed, not the
// saved values. Only ever displayed (escaped), never trusted.
function settingsFormStateFromPost(array $post): array
{
	$submitted = is_array($post["settings"] ?? null) ? $post["settings"] : [];
	$fields = [];

	foreach (settingsScalarFields() as $field) {
		$value = $submitted[$field["key"]] ?? "";
		$fields[$field["key"]] = is_string($value) ? $value : "";
	}

	return [
		"fields" => $fields,
		"processed" => cameraNames($post["process_cameras"] ?? []),
		"flagger" => cameraNames($post["flagger_cameras"] ?? []),
	];
}

// Whole-number text becomes an int; anything else stays text, so the writer's message names the
// problem instead of PHP guessing.
function settingsInputValue(string $text): int|string
{
	$text = trim($text);

	return preg_match('/^[0-9]{1,9}$/D', $text) === 1 ? (int) $text : $text;
}

// The ticked names, sorted and without duplicates, or null when anything is not a known camera.
function settingsCheckedCameras(mixed $names, array $knownCameras): ?array
{
	if (!is_array($names)) {
		return null;
	}

	foreach ($names as $name) {
		if (!is_string($name) || !in_array($name, $knownCameras, true)) {
			return null;
		}
	}

	$checked = array_values(array_unique($names));

	sort($checked, SORT_NATURAL | SORT_FLAG_CASE);

	return $checked;
}

// [values, problems]: the nested values the writer validates, or the reasons nothing is sent. The
// form's fixed field list is the only thing read: a posted key that is not in it never gets here.
function settingsValuesFromPost(array $post, array $knownCameras): array
{
	$submitted = $post["settings"] ?? null;

	if (!is_array($submitted)) {
		return [[], [SETTINGS_FORM_INCOMPLETE]];
	}

	$values = [];

	foreach (settingsScalarFields() as $field) {
		$text = $submitted[$field["key"]] ?? null;

		if (!is_string($text)) {
			return [[], [SETTINGS_FORM_INCOMPLETE]];
		}

		setSettingsLeaf($values, $field["key"], $field["type"] === "time" ? trim($text) : settingsInputValue($text));
	}

	// An unticked box is not sent at all, so a missing list means nothing is ticked.
	$processed = settingsCheckedCameras($post["process_cameras"] ?? [], $knownCameras);
	$flagger = settingsCheckedCameras($post["flagger_cameras"] ?? [], $knownCameras);

	if ($processed === null || $flagger === null) {
		return [[], ["Die ausgewählte Kamera ist ungültig."]];
	}

	// With every camera ignored the night run would process nothing.
	if ($processed === []) {
		return [[], ["Mindestens eine Kamera muss angehakt bleiben."]];
	}

	$values["ignored_cameras"] = array_values(array_diff($knownCameras, $processed));
	setSettingsLeaf($values, "flagger.cameras", $flagger);

	return [$values, []];
}

// The writer's messages start with the dotted key ("timelapse.crf: ..."). Returns [messages by
// field key, the others]: the first are shown next to their field, all of them in the summary.
function settingsSplitErrors(array $errors): array
{
	$labels = [];

	foreach (settingsScalarFields() as $field) {
		$labels[$field["key"]] = $field["label"];
	}

	$byKey = [];
	$general = [];

	foreach ($errors as $error) {
		$parts = explode(": ", (string) $error, 2);

		if (count($parts) === 2 && isset($labels[$parts[0]])) {
			$byKey[$parts[0]] = $parts[1];
		} else {
			$general[] = (string) $error;
		}
	}

	return [$byKey, $general];
}

// The saved modification time as the colleagues read it, in the cameras' timezone. Empty when the
// settings were never saved on the page.
function formatSettingsTime(int $mtime): string
{
	if ($mtime <= 0) {
		return "";
	}

	$timezone = readProjectConfig()["location"]["timezone"] ?? null;

	// Checked up front: with Xdebug loaded (as on the CI runner) an invalid name would turn the
	// constructor's exception into an Error.
	$zone = in_array($timezone, DateTimeZone::listIdentifiers(), true)
		? new DateTimeZone($timezone)
		: new DateTimeZone("UTC");

	return (new DateTimeImmutable("@" . $mtime))->setTimezone($zone)->format("d.m.Y, H:i");
}

// One labelled input with its unit hint, the config.json value as "Standard", and its error.
function renderSettingsField(array $field, array $state, array $baseConfig, array $fieldErrors): void
{
	$key = $field["key"];
	$id = settingsFieldId($key);
	$error = $fieldErrors[$key] ?? null;
	[$hasDefault, $default] = settingsLeaf($baseConfig, $key);
	$describedBy = implode(" ", array_filter([
		isset($field["hint"]) ? $id . "-hint" : null,
		$error !== null ? $id . "-error" : null,
	]));

	?>
	<div class="settings-field">
		<label for="<?= settingsHtml($id) ?>"><?= settingsHtml($field["label"]) ?></label>
		<?php if (isset($field["slider_step"])): ?>
		<?php // A slider only helps the mouse: the field is the real control and the only one sent. ?>
		<div class="privacy-slider-row">
			<input
				type="range"
				class="privacy-range"
				data-slider-for="<?= settingsHtml($id) ?>"
				min="<?= settingsSliderBound($field, $field["min"]) ?>"
				max="<?= settingsSliderBound($field, $field["max"]) ?>"
				step="<?= (int) $field["slider_step"] ?>"
				aria-hidden="true"
				tabindex="-1"
				hidden
			>
		<?php endif; ?>
		<input
			type="<?= settingsHtml($field["type"]) ?>"
			id="<?= settingsHtml($id) ?>"
			name="settings[<?= settingsHtml($key) ?>]"
			value="<?= settingsHtml($state["fields"][$key] ?? "") ?>"
			<?= $hasDefault && (is_int($default) || is_string($default)) ? 'data-default="' . settingsHtml((string) $default) . '"' : "" ?>
			<?php if (isset($field["min"])): ?>
				min="<?= settingsHtml((string) $field["min"]) ?>" max="<?= settingsHtml((string) $field["max"]) ?>"
			<?php endif; ?>
			<?php if ($field["type"] === "number"): ?>
				step="1" inputmode="numeric"
			<?php endif; ?>
			required
			<?= $error !== null ? 'aria-invalid="true"' : "" ?>
			<?= $describedBy !== "" ? 'aria-describedby="' . settingsHtml($describedBy) . '"' : "" ?>
		>
		<?php if (isset($field["slider_step"])): ?>
		</div>
		<?php endif; ?>
		<?php if ($hasDefault && (is_int($default) || is_string($default))): ?>
			<span class="settings-default">Standard: <?= settingsHtml((string) $default) ?></span>
		<?php endif; ?>
		<?php if (isset($field["hint"])): ?>
			<p class="settings-hint" id="<?= settingsHtml($id) ?>-hint"><?= settingsHtml($field["hint"]) ?></p>
		<?php endif; ?>
		<?php if ($error !== null): ?>
			<p class="field-error" id="<?= settingsHtml($id) ?>-error"><?= settingsHtml($error) ?></p>
		<?php endif; ?>
	</div>
	<?php
}

// The button of one group. A script fills the group's fields with their Standard (it never saves);
// it starts hidden and the script shows it, so without JavaScript nothing is offered that does
// nothing. The label names the group for screen readers and still contains the visible text.
function renderSettingsDefaultButton(string $legend): void
{
	?>
	<button
		type="button"
		class="settings-default-button"
		data-default-group
		hidden
		aria-label="<?= settingsHtml($legend) ?>: auf Standard zurücksetzen"
	>Auf Standard zurücksetzen</button>
	<?php
}

// A list of camera checkboxes (name = the form field, e.g. "process_cameras"). Which cameras are on
// is a choice, not a value, so it has no Standard and the restore buttons leave it alone.
function renderSettingsCameraBoxes(string $name, array $knownCameras, array $ticked): void
{
	?>
	<div class="settings-cameras">
		<?php foreach ($knownCameras as $camera): ?>
			<label>
				<input
					type="checkbox"
					name="<?= settingsHtml($name) ?>[]"
					value="<?= settingsHtml($camera) ?>"
					<?= in_array($camera, $ticked, true) ? "checked" : "" ?>
				>
				<?= settingsHtml($camera) ?>
			</label>
		<?php endforeach; ?>
	</div>
	<?php
}
