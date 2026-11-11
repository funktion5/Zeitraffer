// An instant tooltip for the storage donuts: the browser's own title tooltip only appears after a
// delay. The text of each arc sits in its data-tip; screen readers get the ring's aria-label and the list.
(() => {
	const tooltip = document.createElement("div");
	tooltip.className = "storage-tooltip";
	tooltip.hidden = true;
	tooltip.setAttribute("aria-hidden", "true");
	document.body.append(tooltip);

	// Beside the pointer, kept inside the window.
	function place(event) {
		const left = Math.min(event.clientX + 14, window.innerWidth - tooltip.offsetWidth - 8);

		tooltip.style.left = `${Math.max(8, left)}px`;
		tooltip.style.top = `${event.clientY + 18}px`;
	}

	for (const arc of document.querySelectorAll("[data-tip]")) {
		arc.addEventListener("pointermove", (event) => {
			tooltip.textContent = arc.dataset.tip;
			tooltip.hidden = false;
			place(event);
		});

		arc.addEventListener("pointerleave", () => {
			tooltip.hidden = true;
		});
	}
})();
