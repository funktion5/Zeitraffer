// Switches the timelapse period without a page reload. Without JavaScript the
// tabs are plain links, so the page still works.
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
