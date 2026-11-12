<?php

declare(strict_types=1);

require_once __DIR__ . "/../src/json-response.php";
require_once __DIR__ . "/../src/job-state.php";


// Whether any web job is running, for the notice at the top of every page. The details of the job stay
// in the browser tab that started it; this answers only yes or no.
if ($_SERVER["REQUEST_METHOD"] !== "GET") {
	respondWithJson(
		405,
		["error" => "Method not allowed."],
	);
}

respondWithJson(200, ["running" => hasRunningWebJob(webStatusRoot())]);
