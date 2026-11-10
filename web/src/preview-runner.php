<?php

declare(strict_types=1);

require_once __DIR__ . "/process-runner.php";

// The preview picture of a blur camera on the Verpixelung page. A root-owned wrapper fetches one
// confirmed frame from the Storage Box and caches it (state/web-jobs/previews/<camera>.jpg plus a
// <camera>.json with its size); this file starts the wrapper and reads the cache. Nothing in here
// reaches the box itself, and no raw frame: the script behind the wrapper only publishes a frame
// the box blur job has confirmed.

// A camera name as the preview takes it: the plain name the per-camera settings keys allow (no dot,
// no slash), so a name from a request can never leave the cache folder.
const PREVIEW_CAMERA_PATTERN = '/^[A-Za-z0-9][A-Za-z0-9_-]*$/D';

// Sanity limits for what is read back from the cache: the same size bound as the script's.
const PREVIEW_MAX_DIMENSION = 20000;
const PREVIEW_MAX_BYTES = 32 * 1024 * 1024;

// The kinds of frame the script may publish (its "status" in the .json file).
const PREVIEW_KINDS = ["blurred", "clean", "night"];

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

// The cached JPEG of a camera, or null when there is none worth serving: an unsafe name, a missing,
// empty, oversized or linked file (a link could lead anywhere the web server user can read), or
// content that does not start like a JPEG.
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

	$handle = fopen($path, "rb");

	if ($handle === false) {
		return null;
	}

	$start = fread($handle, 2);
	fclose($handle);

	return $start === "\xFF\xD8" ? $path : null;
}

// What the page needs to show the picture: size, kind of frame, when it was taken and a version.
// Null unless the picture AND its description are both there and plausible: the description is
// the page's only knowledge of the picture's size.
function readPreviewInfo(string $camera): ?array
{
	$picture = previewPicturePath($camera);
	$infoPath = previewDirectory() . "/" . $camera . ".json";

	if ($picture === null || is_link($infoPath) || !is_file($infoPath) || !is_readable($infoPath)) {
		return null;
	}

	$content = file_get_contents($infoPath);
	$info = $content === false ? null : json_decode($content, true);

	if (!is_array($info)) {
		return null;
	}

	$width = $info["width"] ?? null;
	$height = $info["height"] ?? null;
	$kind = $info["status"] ?? null;
	$taken = $info["taken"] ?? null;

	foreach ([$width, $height] as $side) {
		if (!is_int($side) || $side < 1 || $side > PREVIEW_MAX_DIMENSION) {
			return null;
		}
	}

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
		"width" => $width,
		"height" => $height,
		"kind" => $kind,
		"taken" => $taken,
		"takenText" => $moment->format("d.m.Y, H:i"),
		"version" => $version === false ? 0 : $version,
	];
}

// The one JSON line the preview script prints, or null when the output is not a JSON object with a
// text "status".
function decodePreviewReply(string $stdout): ?array
{
	$reply = json_decode($stdout, true);

	return is_array($reply) && is_string($reply["status"] ?? null) ? $reply : null;
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

	$reply = decodePreviewReply($result["stdout"]);
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
