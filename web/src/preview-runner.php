<?php

declare(strict_types=1);

require_once __DIR__ . "/process-runner.php";

// The preview picture of a blur camera on the Verpixelung page. A root-owned wrapper fetches one
// confirmed frame from the Storage Box and caches it (state/web-jobs/previews/<camera>.jpg plus a
// <camera>.json saying which frame it is); this file starts the wrapper and reads the cache. Nothing in here
// reaches the box itself, and no raw frame: the script behind the wrapper only publishes a frame
// the box blur job has confirmed.

// A camera name as the preview takes it: the plain name the per-camera settings keys allow (no dot,
// no slash), so a name from a request can never leave the cache folder.
const PREVIEW_CAMERA_PATTERN = '/^[A-Za-z0-9][A-Za-z0-9_-]*$/D';

// Sanity limits for what is read back from the cache: a picture's side is bound the same way as an
// ignore box's coordinates (src/settings.py).
const PREVIEW_MAX_DIMENSION = 20000;
const PREVIEW_MAX_BYTES = 32 * 1024 * 1024;

// The kinds of frame the script may publish ("status" in the .json file). Not "night": the blur
// job records it without running the detector.
const PREVIEW_KINDS = ["blurred", "clean"];

const PREVIEW_OK_MESSAGE = "Das Bild wurde aktualisiert.";
const PREVIEW_NONE_MESSAGE = "Für diese Kamera gibt es noch kein geprüftes Bild. Es entsteht, sobald die Verpixelung in der Nacht Bilder dieser Kamera geprüft hat.";
const PREVIEW_UNKNOWN_MESSAGE = "Diese Kamera wird nicht verpixelt.";
const PREVIEW_FAILED_MESSAGE = "Das Bild konnte nicht geholt werden. Bitte später noch einmal versuchen.";
const PREVIEW_TIMEOUT_MESSAGE = "Die Speicherbox hat nicht rechtzeitig geantwortet. Bitte später noch einmal versuchen.";

function isPreviewCamera(string $camera): bool
{
	return preg_match(PREVIEW_CAMERA_PATTERN, $camera) === 1;
}

// Whether the camera is on the blur list of the given config (see readProjectConfig()). Only a
// camera that blurs has a preview; a name from a request is checked against this first.
function isBlurCamera(array $config, string $camera): bool
{
	$privacy = $config["privacy"] ?? null;
	$cameras = is_array($privacy) ? ($privacy["blur_cameras"] ?? null) : null;

	return is_array($cameras) && in_array($camera, $cameras, true);
}

function previewDirectory(): string
{
	return dirname(__DIR__, 2) . "/state/web-jobs/previews";
}

// The address the page asks the browser for the picture by. The version changes with the picture,
// so an old one is never shown from the browser's cache.
function previewUrl(string $camera, int $version): string
{
	return "/preview.php?camera=" . rawurlencode($camera) . "&v=" . $version;
}

// [width, height] of a cached JPEG, read from the picture itself, or null. getimagesize() also
// reads GIF, PNG and more, so the type is checked; it raises a notice for a damaged file, which
// null already answers, so the notice is dropped here.
function previewPictureSize(string $path): ?array
{
	set_error_handler(static fn(): bool => true);

	try {
		$found = getimagesize($path);
	} finally {
		restore_error_handler();
	}

	if ($found === false || $found[2] !== IMAGETYPE_JPEG) {
		return null;
	}

	[$width, $height] = $found;

	foreach ([$width, $height] as $side) {
		if ($side < 1 || $side > PREVIEW_MAX_DIMENSION) {
			return null;
		}
	}

	return [$width, $height];
}

// The cached JPEG of a camera, or null when there is none worth serving: an unsafe name, a missing,
// empty, oversized or linked file (a link could lead anywhere the web server user can read), or a
// file that is not a JPEG of a plausible size.
function previewPicturePath(string $camera): ?string
{
	if (!isPreviewCamera($camera)) {
		return null;
	}

	$path = previewDirectory() . "/" . $camera . ".jpg";

	if (is_link($path) || !is_file($path) || !is_readable($path)) {
		return null;
	}

	$size = filesize($path);

	if ($size === false || $size < 4 || $size > PREVIEW_MAX_BYTES) {
		return null;
	}

	return previewPictureSize($path) === null ? null : $path;
}

// What the page needs to show the picture. Null unless the picture AND its description are
// both there and plausible.
function readPreviewInfo(string $camera): ?array
{
	$picture = previewPicturePath($camera);
	$size = $picture === null ? null : previewPictureSize($picture);
	$infoPath = previewDirectory() . "/" . $camera . ".json";

	if ($picture === null || $size === null || is_link($infoPath) || !is_file($infoPath) || !is_readable($infoPath)) {
		return null;
	}

	$content = file_get_contents($infoPath);
	$info = $content === false ? null : json_decode($content, true);

	if (!is_array($info)) {
		return null;
	}

	$kind = $info["status"] ?? null;
	$taken = $info["taken"] ?? null;

	if (!in_array($kind, PREVIEW_KINDS, true) || !is_string($taken)) {
		return null;
	}

	// createFromFormat answers false for a text that is not a date, without throwing.
	$moment = DateTimeImmutable::createFromFormat(DATE_ATOM, $taken);

	if ($moment === false) {
		return null;
	}

	$version = filemtime($picture);

	return [
		"width" => $size[0],
		"height" => $size[1],
		"kind" => $kind,
		"taken" => $taken,
		"takenText" => $moment->format("d.m.Y, H:i"),
		"version" => $version === false ? 0 : $version,
	];
}

// The picture only if the page would show it too: a JPEG of a plausible size with a valid
// description naming a judged frame. A night frame cached earlier stays on disk when a refresh
// finds nothing newer, and its description says so.
function previewServablePath(string $camera): ?string
{
	return readPreviewInfo($camera) === null ? null : previewPicturePath($camera);
}

// Alt text and caption are worded once, here, for the page and for the refresh answer: the script
// only shows them.
function previewAltText(string $camera, array $info): string
{
	return "Vorschaubild der Kamera " . $camera . " vom " . $info["takenText"] . " Uhr";
}

function previewCaption(array $info): string
{
	return "Aufgenommen am " . $info["takenText"] . " Uhr. Bildgröße: "
		. $info["width"] . " × " . $info["height"] . " Punkte.";
}

// Fetches a fresh preview through the root-owned wrapper (synchronous: one frame takes seconds).
// Returns ["status" => "ok" | "none" | "unknown" | "failed", "message" => string] and, for "ok",
// "info" from the cache. The picture shown is what this process can read from the cache, not what
// the script says. A failure's details go to the server log only, never into the result.
function refreshPreview(string $camera): array
{
	$answer = static fn(string $status, string $message, ?array $info = null): array => $info === null
		? ["status" => $status, "message" => $message]
		: ["status" => $status, "message" => $message, "info" => $info];

	if (!isPreviewCamera($camera)) {
		return $answer("unknown", PREVIEW_UNKNOWN_MESSAGE);
	}

	$runUser = projectRunUser();

	if ($runUser === null) {
		error_log("Preview wrapper not started: owner of the project folder could not be determined.");

		return $answer("failed", PREVIEW_FAILED_MESSAGE);
	}

	$result = runPrivilegedCommand([
		"/usr/bin/sudo",
		"-n",
		"-u",
		$runUser,
		"/usr/local/sbin/timelapse-web-preview",
		$camera,
	]);
	$exitCode = $result["exitCode"];

	if ($exitCode === null) {
		return $answer("failed", PREVIEW_FAILED_MESSAGE);
	}

	// 124: the wrapper's time limit (coreutils timeout) cut the run off; it has no reply.
	if ($exitCode === 124) {
		return $answer("failed", PREVIEW_TIMEOUT_MESSAGE);
	}

	$reply = decodeStatusReply($result["stdout"]);
	$status = $reply["status"] ?? null;

	// 0 picture cached, 66 not a blur camera, 67 no confirmed frame yet (see the wrapper). A reply
	// that does not belong to its exit code is treated like any other failure.
	if ($exitCode === 0 && $status === "ok") {
		$info = readPreviewInfo($camera);

		if ($info !== null) {
			return $answer("ok", PREVIEW_OK_MESSAGE, $info);
		}

		error_log("Preview script reported success but no readable picture is cached for {$camera}.");

		return $answer("failed", PREVIEW_FAILED_MESSAGE);
	}

	if ($exitCode === 67 && $status === "none") {
		return $answer("none", PREVIEW_NONE_MESSAGE);
	}

	if ($exitCode === 66 && $status === "unknown_camera") {
		return $answer("unknown", PREVIEW_UNKNOWN_MESSAGE);
	}

	error_log("Preview wrapper failed with exit code {$exitCode}: {$result["stderr"]}");

	return $answer("failed", PREVIEW_FAILED_MESSAGE);
}
