// Switches the timelapse period without a page reload and replaces the browser's video controls with
// the player's own bar. Without JavaScript, or in a browser without CSS nesting, the tabs stay plain
// links and the video keeps its native controls, so the page still works.
//
// Everything sits in one function, so the identical copy of this file in the
// f5-webcams plugin cannot clash with it when both are loaded on one page.
(() => {
	// Every text this script shows to visitors; the site's text is German.
	const LABELS = {
		controls: "Videosteuerung",
		play: "Abspielen",
		pause: "Pause",
		seek: "Position im Video",
		stepBack: "Ein Bild zurück",
		stepForward: "Ein Bild vor",
		player: "Zeitraffer-Video",
	};

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

	const SVG_NAMESPACE = "http://www.w3.org/2000/svg";
	const ICONS = {
		play: "M8 5v14l11-7z",
		pause: "M6 5h4v14H6zM14 5h4v14h-4z",
		stepBack: "M6 6h2v12H6zm3.5 6l8.5 6V6z",
		stepForward: "M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z",
	};

	// A 24x24 icon from path data. It is decorative: the button carries the text label.
	const icon = (pathData) => {
		const svg = document.createElementNS(SVG_NAMESPACE, "svg");
		const path = document.createElementNS(SVG_NAMESPACE, "path");

		svg.setAttribute("viewBox", "0 0 24 24");
		svg.setAttribute("aria-hidden", "true");
		svg.setAttribute("focusable", "false");
		path.setAttribute("d", pathData);
		svg.append(path);

		return svg;
	};

	const iconButton = (className, label, pathData) => {
		const element = document.createElement("button");

		element.type = "button";
		element.className = className;
		element.setAttribute("aria-label", label);
		element.append(icon(pathData));

		return element;
	};

	// Builds the control bar inside one player and wires it to that player's video.
	const initPlayer = (root) => {
		const viewport = root.querySelector(".timelapse-viewport");
		const video = root.querySelector(".timelapse-video");

		// Where the bar cannot be built or styled, the native controls stay.
		if (!viewport || !video || !CSS.supports("selector(&)")) {
			return;
		}

		const seek = document.createElement("input");

		seek.type = "range";
		seek.className = "timelapse-seek";
		seek.min = "0";
		seek.step = "any";
		seek.value = "0";
		seek.setAttribute("aria-label", LABELS.seek);

		const time = document.createElement("span");

		time.className = "timelapse-time";

		const seekRow = document.createElement("div");

		seekRow.className = "timelapse-seekrow";
		seekRow.append(seek, time);

		const play = iconButton("timelapse-play", LABELS.play, ICONS.play);
		const stepBack = iconButton("timelapse-step-back", LABELS.stepBack, ICONS.stepBack);
		const stepForward = iconButton("timelapse-step-forward", LABELS.stepForward, ICONS.stepForward);
		const steps = document.createElement("div");

		steps.className = "timelapse-steps";
		steps.append(stepBack, stepForward);

		const controls = document.createElement("div");

		controls.className = "timelapse-controls";
		controls.append(play, steps);

		const bar = document.createElement("div");

		bar.className = "timelapse-bar";
		bar.setAttribute("role", "group");
		bar.setAttribute("aria-label", LABELS.controls);
		bar.append(seekRow, controls);

		// While the thumb is dragged, the video's own position must not pull it back.
		let scrubbing = false;

		const refresh = () => {
			const duration = Number.isFinite(video.duration) ? video.duration : 0;
			const current = Math.min(video.currentTime, duration);

			seek.max = String(duration);

			if (!scrubbing) {
				seek.value = String(current);
			}

			// The stylesheet draws the filled part of the track from this value.
			const progress = duration > 0 ? (current / duration) * 100 : 0;

			seek.style.setProperty("--timelapse-progress", `${progress}%`);
			seek.setAttribute("aria-valuetext", valueText(video.currentTime, video.duration));
			time.textContent = `${formatTime(video.currentTime)} / ${formatTime(video.duration)}`;
		};

		const showPlayState = () => {
			const playing = !video.paused && !video.ended;

			play.setAttribute("aria-label", playing ? LABELS.pause : LABELS.play);
			play.firstElementChild.replaceWith(icon(playing ? ICONS.pause : ICONS.play));
		};

		const togglePlay = () => {
			if (video.paused || video.ended) {
				// A load() that interrupts a play() rejects the promise; there is nothing to do about it.
				video.play().catch(() => {});
			} else {
				video.pause();
			}
		};

		// The frame rate of the video on show: it comes with the active tab, so a tab switch changes it.
		const currentFps = () => {
			const active = root.querySelector(".timelapse-tabs a[aria-current]");

			return Number(active && active.dataset.fps);
		};

		// Without a usable frame rate a step would be a guess, so the buttons are hidden instead.
		const showSteps = () => {
			steps.hidden = !(currentFps() > 0);
		};

		const step = (direction) => {
			const fps = currentFps();

			if (!(fps > 0)) {
				return;
			}

			video.pause();
			video.currentTime = stepTime(video.currentTime, direction, fps, video.duration);
		};

		// Keys act only while the picture area itself has focus: the scrubber and the buttons keep their
		// own keys (arrows move the slider, Space presses a button).
		viewport.tabIndex = 0;
		viewport.setAttribute("role", "group");
		viewport.setAttribute("aria-label", LABELS.player);
		viewport.addEventListener("keydown", (event) => {
			if (event.target !== viewport) {
				return;
			}

			if (event.key === " ") {
				event.preventDefault();
				togglePlay();
			} else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
				event.preventDefault();
				step(event.key === "ArrowLeft" ? -1 : 1);
			}
		});

		stepBack.addEventListener("click", () => step(-1));
		stepForward.addEventListener("click", () => step(1));

		seek.addEventListener("pointerdown", () => {
			scrubbing = true;
		});
		["pointerup", "pointercancel"].forEach((name) => {
			seek.addEventListener(name, () => {
				scrubbing = false;
			});
		});
		seek.addEventListener("input", () => {
			video.currentTime = Number(seek.value);
		});
		play.addEventListener("click", togglePlay);
		video.addEventListener("click", togglePlay);

		["loadedmetadata", "durationchange", "timeupdate", "seeked", "emptied"].forEach((name) => {
			video.addEventListener(name, refresh);
		});
		["play", "pause", "ended", "emptied"].forEach((name) => {
			video.addEventListener(name, showPlayState);
		});
		// A tab switch loads another video, maybe with another frame rate.
		video.addEventListener("emptied", showSteps);

		viewport.append(bar);
		video.removeAttribute("controls");
		refresh();
		showPlayState();
		showSteps();
	};

	const start = () => {
		document.querySelectorAll(".timelapse").forEach(initPlayer);
	};

	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", start);
	} else {
		start();
	}

	document.querySelectorAll(".timelapse-tabs a").forEach((link) => {
		link.addEventListener("click", (event) => {
			// Each player is looked up inside its own root, so several players on one page stay apart.
			const root = link.closest(".timelapse");
			const video = root && root.querySelector(".timelapse-video");

			// No player or no data: let the link work as a normal page load.
			if (!video || !link.dataset.src) {
				return;
			}

			event.preventDefault();

			video.src = link.dataset.src;
			video.setAttribute("aria-label", link.dataset.label);
			video.load();

			// The heading shows the time span of the video that is playing.
			const dateEl = root.querySelector(".timelapse-date");
			if (dateEl && link.dataset.date) {
				dateEl.textContent = link.dataset.date;
			}

			root.querySelectorAll(".timelapse-tabs a").forEach((other) => {
				other.removeAttribute("aria-current");
			});
			link.setAttribute("aria-current", "true");

			// Keep the address in sync, so reloading or sharing shows the same period.
			history.replaceState(null, "", link.href);
		});
	});
})();
