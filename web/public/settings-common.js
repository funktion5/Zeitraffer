// Shared by the two settings pages: the slider next to a field, the restore buttons, "Änderungen
// verwerfen". A page passes what is its own: onRestore(scope) once the Standard values are in,
// onReset() once the loaded values are back. Looks only below the form, never submits it.
window.SettingsForm = (() => {
	// The slider of a time field counts minutes since midnight, the slider of a number field the
	// number itself.
	const toMinutes = (text) => {
		const [hours, minutes] = text.split(":").map(Number);

		return hours * 60 + minutes;
	};
	const toClock = (total) =>
		`${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;

	const init = (form, { onRestore = () => {}, onReset = () => {} } = {}) => {
		const note = form.querySelector("#settings-default-note");

		// A slider only helps the mouse: the field is the real control, so both follow each other.
		const fieldOf = (range) => form.querySelector(`#${range.dataset.sliderFor}`);
		const syncSlider = (range) => {
			const field = fieldOf(range);

			if (field.value !== "") {
				range.value = field.type === "time" ? String(toMinutes(field.value)) : field.value;
			}
		};
		const sliders = Array.from(form.querySelectorAll("[data-slider-for]"));

		sliders.forEach((range) => {
			const field = fieldOf(range);

			range.hidden = false;
			range.addEventListener("input", () => {
				field.value = field.type === "time" ? toClock(Number(range.value)) : range.value;
			});
			field.addEventListener("input", () => syncSlider(range));
			syncSlider(range);
		});

		// Fills the fields of one scope with their Standard (the config.json value). Nothing is
		// saved: the Save button stores it, and a value equal to the Standard drops its override.
		const restoreDefaults = (scope, what) => {
			scope.querySelectorAll("[data-default]").forEach((input) => {
				input.value = input.dataset.default;
				// A script sets no "input" event by itself: announce it, so a slider follows.
				input.dispatchEvent(new Event("input"));
			});

			scope.querySelectorAll("[data-default-checked]").forEach((input) => {
				input.checked = input.dataset.defaultChecked === "1";
			});

			onRestore(scope);

			note.textContent = `${what}: Standardwerte eingetragen. Zum Übernehmen bitte speichern.`;
			note.hidden = false;
		};

		// Without JavaScript the buttons stay hidden: they would do nothing.
		form.querySelectorAll("[data-default-group]").forEach((button) => {
			const fieldset = button.closest("fieldset");

			button.hidden = false;
			button.addEventListener("click", () => {
				restoreDefaults(fieldset, fieldset.querySelector("legend").textContent);
			});
		});

		const allButton = form.querySelector("[data-default-all]");

		allButton.hidden = false;
		allButton.addEventListener("click", () => restoreDefaults(form, "Alle Abschnitte"));

		// "Änderungen verwerfen" returns to the loaded values, so the note no longer applies.
		form.addEventListener("reset", () => {
			note.hidden = true;
			// The fields go back to their loaded values after this event, so look then.
			setTimeout(() => {
				sliders.forEach(syncSlider);
				onReset();
			}, 0);
		});
	};

	return { init };
})();
