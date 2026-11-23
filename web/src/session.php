<?php

declare(strict_types=1);


// The session cookie's rules, in one place for every page. HttpOnly: page scripts cannot read it.
// SameSite=Lax: other sites' forms do not carry it. Strict mode: an unknown session ID gets a new
// one. Secure needs HTTPS, so it follows the connection.
function startSession(): void
{
	session_start([
		"cookie_httponly" => true,
		"cookie_samesite" => "Lax",
		"cookie_secure" => ($_SERVER["HTTPS"] ?? "") === "on",
		"use_strict_mode" => true,
	]);
}
