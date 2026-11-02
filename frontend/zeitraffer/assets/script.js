// Switches the timelapse period without a page reload. Without JavaScript the
// tabs are plain links, so the page still works.
//
// Everything sits in one function, so the identical copy of this file in the
// f5-webcams plugin cannot clash with it when both are loaded on one page.
(() => {
	// Pure helpers, free of the DOM so tests/frontend/player.test.js can run them in Node.
	const formatTime = (seconds) => {
		if (!Number.isFinite(seconds) || seconds < 0) {
			return "0:00";
		}

		const whole = Math.floor(seconds);

		return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
	};

	const valueText = (current, duration) => `${formatTime(current)} von ${formatTime(duration)}`;

	// One frame forward or back, landing in the middle of the frame: a seek to the exact
	// frame boundary can show the neighbouring frame because of rounding.
	const stepTime = (current, direction, fps, duration) => {
		if (!(fps > 0)) {
			return current;
		}

		const index = Math.floor(current * fps + 1e-6);
		const target = (index + direction + 0.5) / fps;
		const last = Number.isFinite(duration) ? duration - 0.5 / fps : Infinity;

		return Math.min(Math.max(target, 0.5 / fps), last);
	};

	if (typeof module !== "undefined" && module.exports) {
		module.exports = { formatTime, valueText, stepTime };
	}

	// Loaded by the tests in Node: there is no page to wire up.
	if (typeof document === "undefined") {
		return;
	}

	const video = document.getElementById("zeitraffer_video");

	document.querySelectorAll(".zeitraffer_nav a").forEach((link) => {
		link.addEventListener("click", (event) => {
			// No player or no data: let the link work as a normal page load.
			if (!video || !link.dataset.src) {
				return;
			}

			event.preventDefault();

			video.src = link.dataset.src;
			video.setAttribute("aria-label", link.dataset.label);
			video.load();

			// The heading shows the time span of the video that is playing.
			const dateEl = document.getElementById("zeitraffer_date");
			if (dateEl && link.dataset.date) {
				dateEl.textContent = link.dataset.date;
			}

			document.querySelectorAll(".zeitraffer_nav a").forEach((other) => {
				other.removeAttribute("aria-current");
			});
			link.setAttribute("aria-current", "true");

			// Keep the address in sync, so reloading or sharing shows the same period.
			history.replaceState(null, "", link.href);
		});
	});
})();
