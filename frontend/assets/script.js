// Switches the timelapse period without a page reload. Without JavaScript the
// tabs are plain links, so the page still works.
document.querySelectorAll(".zeitraffer_nav a").forEach(function (link) {
	link.addEventListener("click", function (event) {
		var video = document.getElementById("zeitraffer_video");

		// No player or no data: let the link work as a normal page load.
		if (!video || !link.dataset.src) {
			return;
		}

		event.preventDefault();

		video.src = link.dataset.src;
		video.setAttribute("aria-label", link.dataset.label);
		video.load();

		document.querySelectorAll(".zeitraffer_nav a").forEach(function (other) {
			other.removeAttribute("aria-current");
		});
		link.setAttribute("aria-current", "true");

		// Keep the address in sync, so reloading or sharing shows the same period.
		history.replaceState(null, "", link.href);
	});
});
