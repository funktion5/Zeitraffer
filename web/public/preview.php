<?php

declare(strict_types=1);

require_once __DIR__ . "/../src/video-library.php";
require_once __DIR__ . "/../src/preview-runner.php";

// The cached preview picture of a blur camera, as a JPEG and nothing else. The name is a plain
// name, the camera is on the blur list, and the file is the one the preview script wrote, and only
// when the page would show it too (a judged frame with a valid description): the request never names
// a path.

function respondWithoutPicture(int $statusCode): never
{
	http_response_code($statusCode);
	header("Content-Type: text/plain; charset=UTF-8");
	header("Cache-Control: no-store");

	echo "Kein Bild.";

	exit;
}

if ($_SERVER["REQUEST_METHOD"] !== "GET") {
	header("Allow: GET");

	respondWithoutPicture(405);
}

$camera = $_GET["camera"] ?? null;

if (!is_string($camera) || !isPreviewCamera($camera)) {
	respondWithoutPicture(400);
}

if (!isBlurCamera(readProjectConfig(), $camera)) {
	respondWithoutPicture(404);
}

$path = previewServablePath($camera);
$size = $path === null ? false : filesize($path);

if ($path === null || $size === false) {
	respondWithoutPicture(404);
}

// A picture of a camera: this user's browser may keep it, but has to ask again before showing it.
header("Content-Type: image/jpeg");
header("Content-Length: " . $size);
header("Cache-Control: private, no-cache");
header("X-Content-Type-Options: nosniff");

readfile($path);
