// Switches the timelapse period without a page reload. Without JavaScript the
// tabs are plain links, so the page still works.
const video = document.getElementById("zeitraffer_video");
const player = document.querySelector(".zeitraffer_player");

// Shows the CSS skeleton and tells assistive tech the player is busy.
const setLoading = (loading) => {
	if (!video || !player) {
		return;
	}
	player.classList.toggle("is-loading", loading);
	video.setAttribute("aria-busy", loading ? "true" : "false");
};

if (video && player) {
	// "loadedmetadata", not "loadeddata": with preload="metadata" some browsers never
	// fetch the first frame, which would leave the skeleton up forever. "suspend" covers
	// browsers (e.g. iOS low-power mode) that skip loading until the user presses play.
	["loadedmetadata", "suspend", "error"].forEach((name) => {
		video.addEventListener(name, () => setLoading(false));
	});

	// The video may already have its metadata by the time this script runs.
	if (video.readyState < 1) {
		setLoading(true);
	}
}

document.querySelectorAll(".zeitraffer_nav a").forEach((link) => {
	link.addEventListener("click", (event) => {
		// No player or no data: let the link work as a normal page load.
		if (!video || !link.dataset.src) {
			return;
		}

		event.preventDefault();

		setLoading(true);
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
