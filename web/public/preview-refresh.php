<?php

declare(strict_types=1);
session_start();

require_once __DIR__ . "/../src/json-response.php";
require_once __DIR__ . "/../src/video-library.php";
require_once __DIR__ . "/../src/preview-runner.php";

// "Vorschau aktualisieren" on the Verpixelung page: asks the wrapper for a fresh picture of one blur
// camera and answers with one JSON object. The request needs the session's token like every other
// action, because it makes the server ask the Storage Box for a file.

if ($_SERVER["REQUEST_METHOD"] !== "POST") {
	respondWithJson(405, ["status" => "failed", "message" => "Nicht erlaubt."]);
}

$sessionToken = $_SESSION["csrf_token"] ?? null;

// A session stays locked until it is closed, and the fetch below can take a minute: the colleague's
// other tabs must not wait for it.
session_write_close();

$submittedToken = $_POST["csrf_token"] ?? null;

if (!is_string($sessionToken) || !is_string($submittedToken) || !hash_equals($sessionToken, $submittedToken)) {
	respondWithJson(403, ["status" => "failed", "message" => "Die Anfrage ist ungültig (Sicherheitstoken)."]);
}

$camera = $_POST["camera"] ?? null;

if (!is_string($camera) || !isPreviewCamera($camera) || !isBlurCamera(readProjectConfig(), $camera)) {
	respondWithJson(404, ["status" => "unknown", "message" => PREVIEW_UNKNOWN_MESSAGE]);
}

$result = refreshPreview($camera);
$payload = ["status" => $result["status"], "message" => $result["message"]];

if ($result["status"] === "ok") {
	$info = $result["info"];
	$payload["picture"] = [
		"url" => previewUrl($camera, $info["version"]),
		"width" => $info["width"],
		"height" => $info["height"],
		"takenText" => $info["takenText"],
	];
}

respondWithJson(
	match ($result["status"]) {
		"ok", "none" => 200,
		"unknown" => 404,
		default => 502,
	},
	$payload,
);
