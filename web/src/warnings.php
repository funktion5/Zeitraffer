<?php

declare(strict_types=1);

// The warnings banner: the night's messages written by src/night_warnings.py, the blur watchdog's
// status (src/privacy/blur_watch.py) and two live checks. A missing, broken or old file is never "fine".
// Needs projectRoot() and readProjectConfig() from video-library.php.

const BANNER_NIGHT_DUE_HOUR = 6;
const BANNER_WATCH_MAX_AGE_SECONDS = 15 * 60;

function bannerStateRoot(): string
{
	return getenv("TIMELAPSE_WEB_STATUS_ROOT") ?: projectRoot() . "/state/web-jobs";
}

// The file's JSON object, or null when it is missing, unreadable or not an object.
function readBannerJson(string $name): ?array
{
	$path = bannerStateRoot() . "/" . $name;

	if (!is_file($path) || !is_readable($path)) {
		return null;
	}

	$data = json_decode((string) file_get_contents($path), true);

	return is_array($data) && !array_is_list($data) ? $data : null;
}

// Python writes isoformat(), with or without fractions of a second; anything else is null.
function parseBannerTime(mixed $value): ?DateTimeImmutable
{
	if (!is_string($value)) {
		return null;
	}

	foreach ([DATE_ATOM, "Y-m-d\\TH:i:s.uP"] as $format) {
		$time = DateTimeImmutable::createFromFormat($format, $value);

		if ($time !== false) {
			return $time;
		}
	}

	return null;
}

function bannerMessage(?string $camera, string $text, string $hint): array
{
	return ["camera" => $camera, "text" => $text, "hint" => $hint];
}

// The night's messages as written, keeping only well-formed entries.
function nightMessages(array $night): array
{
	$messages = [];

	foreach (is_array($night["messages"] ?? null) ? $night["messages"] : [] as $entry) {
		$camera = is_array($entry) ? ($entry["camera"] ?? null) : null;

		if (is_array($entry) && is_string($entry["text"] ?? null) && is_string($entry["hint"] ?? null)
			&& ($camera === null || is_string($camera))) {
			$messages[] = bannerMessage($camera, $entry["text"], $entry["hint"]);
		}
	}

	return $messages;
}

// "18.11.2026, 02:00–02:55 Uhr", or the date alone for a night that did not start.
function lastRunText(array $night): ?string
{
	$date = DateTimeImmutable::createFromFormat("!Y-m-d", (string) ($night["date"] ?? ""));
	$started = parseBannerTime($night["started"] ?? null);
	$finished = parseBannerTime($night["finished"] ?? null);

	if ($started !== null && $finished !== null) {
		return $started->format("d.m.Y, H:i") . "–" . $finished->format("H:i") . " Uhr";
	}

	return $date !== false ? $date->format("d.m.Y") . ", nicht gestartet" : null;
}

function bannerNow(): DateTimeImmutable
{
	$timezone = readProjectConfig()["location"]["timezone"] ?? "Europe/Berlin";

	return new DateTimeImmutable("now", new DateTimeZone(is_string($timezone) ? $timezone : "Europe/Berlin"));
}

/**
 * @return array{messages: list<array{camera: ?string, text: string, hint: string}>, lastRun: ?string}
 */
function bannerMessages(DateTimeImmutable $now, ?array $storage): array
{
	$messages = [];
	$lastRun = null;
	$warnings = readBannerJson("warnings.json");
	$night = is_array($warnings["night"] ?? null) && is_array($warnings["messages"] ?? null)
		? $warnings
		: null;
	$nightMissing = "Handbuch „Heute Nacht lief nichts“";

	if ($night === null) {
		$messages[] = bannerMessage(null, "Nachtlauf fehlt", $nightMissing);
	} else {
		$lastRun = lastRunText($night["night"]);
		// Before 06:00 tonight's run may still be going, so last night's file still counts; no older one.
		$date = $night["night"]["date"] ?? null;
		$isToday = $date === $now->format("Y-m-d");
		$isYesterday = $date === $now->modify("-1 day")->format("Y-m-d");
		$beforeDue = $now < $now->setTime(BANNER_NIGHT_DUE_HOUR, 0);

		if (!$isToday && !($beforeDue && $isYesterday)) {
			$messages[] = bannerMessage(null, "Nachtlauf fehlt", $nightMissing);
		} else {
			$messages = nightMessages($night);
		}
	}

	$watch = readBannerJson("blur-watch.json");
	$checked = parseBannerTime($watch["checked"] ?? null);

	if ($checked === null || $now->getTimestamp() - $checked->getTimestamp() > BANNER_WATCH_MAX_AGE_SECONDS) {
		$messages[] = bannerMessage(null, "Verpixelungs-Wächter läuft nicht", "Cron-Zeile des Wächters prüfen");
	} else {
		if (is_string($watch["error"] ?? null)) {
			$messages[] = bannerMessage(
				null,
				"Verpixelungs-Wächter: " . $watch["error"],
				"Storage Box erreichbar? Handbuch „Verpixelung“",
			);
		}

		foreach (is_array($watch["stale"] ?? null) ? $watch["stale"] : [] as $camera => $count) {
			if (is_int($count) && $count > 0) {
				$messages[] = bannerMessage(
					(string) $camera,
					$count . ($count === 1 ? " Bild" : " Bilder") . " seit über 10 Minuten unverpixelt",
					"Verpixelungs-Protokoll prüfen; Handbuch „Verpixelung“",
				);
			}
		}
	}

	$diskTexts = ["warn" => "Speicher wird knapp", "critical" => "Speicher fast voll"];
	$level = $storage["level"] ?? null;

	if (is_string($level) && isset($diskTexts[$level])) {
		$messages[] = bannerMessage(null, $diskTexts[$level], "Alte Videos löschen; Handbuch „Festplatte voll“");
	}

	return ["messages" => $messages, "lastRun" => $lastRun];
}
