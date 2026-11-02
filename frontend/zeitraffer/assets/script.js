// MASTER COPY. This file lives in the Zeitraffer plugin (frontend/zeitraffer/assets/script.js) and is
// copied word for word to the f5-webcams plugin as assets/js/timelapse.js. Change it here first, copy
// it, and check the copy with:
//   diff frontend/zeitraffer/assets/script.js frontend/f5-webcams/assets/js/timelapse.js
//
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
		speeds: "Wiedergabegeschwindigkeit",
		fullscreen: "Vollbild",
		exitFullscreen: "Vollbild verlassen",
		error: "Das Video konnte nicht geladen werden. Bitte laden Sie die Seite neu oder versuchen Sie es später noch einmal.",
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

	// The start of the frame that is on show: the scrubber moves in whole frames, so its value is
	// this, not the exact (mid-frame) position the video reports.
	const frameStart = (current, fps) => {
		if (!(fps > 0)) {
			return current;
		}

		return Math.floor(current * fps + 1e-6) / fps;
	};

	if (typeof module !== "undefined" && module.exports) {
		module.exports = { formatTime, valueText, stepTime, frameStart };
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
		fullscreen: "M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z",
		exitFullscreen: "M5 16h3v3h2v-5H5v2zm3-8H5v2h5V5H8v3zm6 11h2v-3h3v-2h-5v5zm2-11V5h-2v5h5V8h-3z",
	};

	// The speeds a visitor can pick; the German text uses a decimal comma.
	const SPEEDS = [
		{ rate: 0.5, text: "0,5×" },
		{ rate: 1, text: "1×" },
		{ rate: 2, text: "2×" },
	];

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
		// The tooltip a mouse user gets for an icon, the same words as the label.
		element.title = label;
		element.append(icon(pathData));

		return element;
	};

	// A button whose visible text is its name, for the speeds.
	const textButton = (className, text) => {
		const element = document.createElement("button");

		element.type = "button";
		element.className = className;
		element.textContent = text;

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

		// A second copy of this script (the other plugin's) must not build a second bar.
		if (root.dataset.timelapseReady) {
			return;
		}

		root.dataset.timelapseReady = "true";

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

		const speedGroup = document.createElement("div");

		speedGroup.className = "timelapse-speeds";
		speedGroup.setAttribute("role", "group");
		speedGroup.setAttribute("aria-label", LABELS.speeds);

		const speedButtons = SPEEDS.map(({ rate, text }) => {
			const element = textButton("timelapse-speed", text);

			element.dataset.speed = String(rate);
			element.title = `${LABELS.speeds}: ${text}`;

			return element;
		});

		speedGroup.append(...speedButtons);

		// Narrow players show a dropdown instead of the three buttons (the stylesheet picks which one is
		// visible); both are kept in step by setSpeed.
		const speedSelect = document.createElement("select");

		speedSelect.className = "timelapse-speed-select";
		speedSelect.setAttribute("aria-label", LABELS.speeds);
		speedSelect.title = LABELS.speeds;
		SPEEDS.forEach(({ rate, text }) => {
			const choice = document.createElement("option");

			choice.value = String(rate);
			choice.textContent = text;
			speedSelect.append(choice);
		});

		const speedField = document.createElement("span");

		speedField.className = "timelapse-speed-field";
		speedField.append(speedSelect);

		const fullscreen = iconButton("timelapse-fullscreen", LABELS.fullscreen, ICONS.fullscreen);
		const options = document.createElement("div");

		options.className = "timelapse-options";
		options.append(speedGroup, speedField, fullscreen);
		controls.append(options);

		// Shown over the picture when the video cannot be loaded.
		const error = document.createElement("p");

		error.className = "timelapse-error";
		error.setAttribute("role", "alert");
		error.hidden = true;

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
				seek.value = String(frameStart(current, currentFps()));
			}

			// The stylesheet draws the filled part of the track from this value.
			const progress = duration > 0 ? (current / duration) * 100 : 0;

			seek.style.setProperty("--timelapse-progress", `${progress}%`);
			seek.setAttribute("aria-valuetext", valueText(video.currentTime, video.duration));
			time.textContent = `${formatTime(video.currentTime)} / ${formatTime(video.duration)}`;
		};

		const showPlayState = () => {
			const playing = !video.paused && !video.ended;

			const label = playing ? LABELS.pause : LABELS.play;

			play.setAttribute("aria-label", label);
			play.title = label;
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

		// Without a usable frame rate a step would be a guess, so the buttons are hidden instead. The
		// scrubber then moves in whole frames as well, so one arrow key press is one frame.
		const applyFrameRate = () => {
			const fps = currentFps();

			steps.hidden = !(fps > 0);
			seek.step = fps > 0 ? String(1 / fps) : "any";
		};

		const step = (direction) => {
			const fps = currentFps();

			// A video that failed or has not loaded has no position to step from.
			if (!(fps > 0) || video.readyState < 1) {
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

		const setSpeed = (rate) => {
			// defaultPlaybackRate survives video.load(), so a tab switch keeps the chosen speed.
			video.defaultPlaybackRate = rate;
			video.playbackRate = rate;
			speedButtons.forEach((element) => {
				element.setAttribute("aria-pressed", String(Number(element.dataset.speed) === rate));
			});
			speedSelect.value = String(rate);
		};

		speedSelect.addEventListener("change", () => setSpeed(Number(speedSelect.value)));

		speedButtons.forEach((element) => {
			element.addEventListener("click", () => setSpeed(Number(element.dataset.speed)));
		});
		setSpeed(1);

		// The viewport goes fullscreen, not the bare video, so the bar comes along. Where that is not
		// supported (iPhone), the button is hidden.
		fullscreen.hidden = !viewport.requestFullscreen;

		const showFullscreenState = () => {
			const on = document.fullscreenElement === viewport;

			const label = on ? LABELS.exitFullscreen : LABELS.fullscreen;

			fullscreen.setAttribute("aria-label", label);
			fullscreen.title = label;
			fullscreen.firstElementChild.replaceWith(icon(on ? ICONS.exitFullscreen : ICONS.fullscreen));
		};

		fullscreen.addEventListener("click", () => {
			if (document.fullscreenElement === viewport) {
				document.exitFullscreen();
			} else {
				// A refused request (no user gesture, a policy) leaves the page as it is.
				viewport.requestFullscreen().catch(() => {});
			}
		});
		document.addEventListener("fullscreenchange", showFullscreenState);

		video.addEventListener("error", () => {
			error.textContent = LABELS.error;
			error.hidden = false;
		});
		["emptied", "loadedmetadata"].forEach((name) => {
			video.addEventListener(name, () => {
				error.hidden = true;
			});
		});

		seek.addEventListener("pointerdown", () => {
			scrubbing = true;
		});
		["pointerup", "pointercancel"].forEach((name) => {
			seek.addEventListener(name, () => {
				scrubbing = false;
			});
		});
		seek.addEventListener("input", () => {
			// Into the middle of the chosen frame, as the frame step does (see stepTime).
			video.currentTime = stepTime(Number(seek.value), 0, currentFps(), video.duration);
		});
		play.addEventListener("click", togglePlay);


		// In fullscreen the bar fades away while the video plays and nobody touches anything for a few
		// seconds, so it does not cover the picture. The first tap on the picture then only brings it
		// back; a tap while it is visible plays or pauses, as everywhere else.
		const IDLE_MS = 3000;
		let idleTimer;
		let revealOnly = false;

		const wake = () => {
			bar.classList.remove("timelapse-idle");
			clearTimeout(idleTimer);

			if (!video.paused && document.fullscreenElement === viewport) {
				idleTimer = setTimeout(() => {
					// Only a keyboard focus keeps the bar: a clicked or tapped button keeps focus too.
					if (!bar.querySelector(":focus-visible")) {
						bar.classList.add("timelapse-idle");
					}
				}, IDLE_MS);
			}
		};

		["pointerdown", "pointermove", "keydown", "focusin"].forEach((name) => {
			viewport.addEventListener(name, wake);
		});
		["play", "pause", "ended", "emptied"].forEach((name) => {
			video.addEventListener(name, wake);
		});
		document.addEventListener("fullscreenchange", wake);
		// Captured, so it still sees the bar as hidden before wake() shows it again.
		viewport.addEventListener(
			"pointerdown",
			() => {
				revealOnly = bar.classList.contains("timelapse-idle");
			},
			true,
		);
		video.addEventListener("click", () => {
			if (revealOnly) {
				revealOnly = false;

				return;
			}

			togglePlay();
		});

		["loadedmetadata", "durationchange", "timeupdate", "seeked", "emptied"].forEach((name) => {
			video.addEventListener(name, refresh);
		});
		["play", "pause", "ended", "emptied"].forEach((name) => {
			video.addEventListener(name, showPlayState);
		});
		// A tab switch loads another video, maybe with another frame rate.
		video.addEventListener("emptied", applyFrameRate);

		viewport.append(bar, error);
		video.removeAttribute("controls");
		refresh();
		showPlayState();
		applyFrameRate();

		// The video may have failed before this script got to it.
		if (video.error) {
			error.textContent = LABELS.error;
			error.hidden = false;
		}
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
		// The identical script of the other plugin may be loaded too: one handler per link is enough.
		if (link.dataset.timelapseTab) {
			return;
		}

		link.dataset.timelapseTab = "true";

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

			// Keep the address in sync, so reloading or sharing shows the same period. Only the first
			// player on a page does it: several players would overwrite each other's period.
			if (root === document.querySelector(".timelapse")) {
				history.replaceState(null, "", link.href);
			}
		});
	});
})();
