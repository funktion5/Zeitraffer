<?php

declare(strict_types=1);


// Return one JSON response and stop processing.
function respondWithJson(int $statusCode, array $payload): never
{
	http_response_code($statusCode);
	header("Content-Type: application/json; charset=UTF-8");
	header("Cache-Control: no-store");

	echo json_encode(
		$payload,
		JSON_THROW_ON_ERROR,
	);

	exit;
}
