// Script of the Verpixelung page: box rows, drawing editor, "Vorschau aktualisieren", confirm
// dialog. Slider, restore buttons and reset come from settings-common.js (loaded first). Reads only
// the page's own DOM.
(() => {
	const form = document.querySelector(".settings-form");
	const dialog = document.querySelector("#privacy-confirm");

	// The four number inputs of a box row, in the order left, top, right, bottom, and a way to write
	// a box's numbers into them.
	const cellsOf = (row) => Array.from(row.querySelectorAll("input"));
	const fillRow = (row, cells) => {
		cellsOf(row).forEach((input, position) => {
			input.value = String(cells[position]);
		});
	};

	// One more row of four box numbers, cloned from the camera's template.
	const addBoxRow = (container, cells = ["", "", "", ""]) => {
		const template = container.closest("fieldset").querySelector("[data-box-template]");
		const index = Number(container.dataset.nextIndex);

		container.dataset.nextIndex = String(index + 1);
		container.insertAdjacentHTML(
			"beforeend",
			template.innerHTML
				.replaceAll("__INDEX__", String(index))
				.replaceAll("__NUMBER__", String(index + 1)),
		);

		const row = container.lastElementChild;

		fillRow(row, cells);
		row.querySelector("[data-remove-box]").hidden = false;
	};

	// Without JavaScript these buttons stay hidden: they would do nothing.
	form.querySelectorAll("[data-remove-box]").forEach((button) => {
		button.hidden = false;
	});
	// What a screen reader hears after a row was added or removed.
	const announce = (container, text) => {
		sectionOf(container).querySelector("[data-preview-status]").textContent =
			`${text} Zum Übernehmen unten auf „Speichern“ drücken.`;
	};
	form.addEventListener("click", (event) => {
		const remove = event.target.closest("[data-remove-box]");

		if (remove !== null) {
			const container = remove.closest(".privacy-boxes");
			const row = remove.closest(".privacy-box-row");
			const rows = Array.from(container.querySelectorAll(".privacy-box-row"));
			const position = rows.indexOf(row);
			// The focused button goes with its row: the focus moves to the next row, else the one
			// before, else to "Rahmen hinzufügen".
			const neighbour = rows[position + 1] ?? rows[position - 1];

			row.remove();
			refreshContainer(container);
			(neighbour === undefined
				? container.closest("fieldset").querySelector("[data-add-box]")
				: cellsOf(neighbour)[0]
			).focus();
			announce(container, `Rahmen ${position + 1} wurde entfernt.`);
		}
	});
	form.querySelectorAll("[data-add-box]").forEach((button) => {
		button.hidden = false;
		button.addEventListener("click", () => {
			const container = button.closest("fieldset").querySelector(".privacy-boxes");

			addBoxRow(container);
			refreshContainer(container);
			cellsOf(container.lastElementChild)[0].focus();
			announce(container, `Rahmen ${container.querySelectorAll(".privacy-box-row").length} ist dazugekommen.`);
		});
	});

	// The drawing editor: a layer of plain boxes over the picture, in percent of its size. The rows of
	// numbers stay the real control (also without a mouse); the layer only shows them and adds rows
	// from a drag. The strip reads and writes this camera's own top-share field and slider.
	const topFieldOf = (section) => section.closest("fieldset").querySelector('input[name^="privacy[top]["]');
	const topRangeOf = (section) =>
		section.closest("fieldset").querySelector(`[data-slider-for="${topFieldOf(section).id}"]`);

	// The strip counts only while the field holds a usable number.
	const currentShare = (section) => {
		const field = topFieldOf(section);
		const value = Number(field.value);

		return field.value.trim() !== "" && value > 0 && value < 0.5 ? value : 0;
	};

	const setTopShare = (section, value) => {
		topFieldOf(section).value = String(value);
		topRangeOf(section).value = String(value);
		redrawSection(section);
	};

	// Smaller than this (in screen pixels) is a click or a slip of the hand, not a box.
	const MIN_DRAWN_SIDE = 6;

	const sectionOf = (container) => container.closest("fieldset").querySelector("[data-preview-camera]");
	const containerOf = (section) => section.closest("fieldset").querySelector(".privacy-boxes");
	const percent = (part, whole) => `${(part / whole) * 100}%`;

	// The picture's own size is the width and height of its image: the one place the page keeps it.
	const pictureSize = (section) => {
		const image = section.querySelector(".privacy-preview-stage img");
		const width = Number(image?.getAttribute("width"));
		const height = Number(image?.getAttribute("height"));

		return width > 0 && height > 0 ? { width, height } : null;
	};

	// A row as a box, or null while it is blank or not a usable box yet.
	const boxOfRow = (row) => {
		const inputs = cellsOf(row);

		if (inputs.some((input) => input.value.trim() === "")) {
			return null;
		}

		const [x0, y0, x1, y1] = inputs.map((input) => Number(input.value));

		return [x0, y0, x1, y1].every(Number.isFinite) && x1 > x0 && y1 > y0 ? { x0, y0, x1, y1 } : null;
	};

	// The rows count 1, 2, 3 ... in the order they stand, also after one was removed or added: a
	// rectangle on the picture carries the same number.
	const numberRows = (container) => {
		container.querySelectorAll(".privacy-box-row").forEach((row, index) => {
			const number = String(index + 1);

			row.querySelector(".privacy-box-number").textContent = number;
			cellsOf(row).forEach((input) => {
				input.setAttribute("aria-label", input.getAttribute("aria-label").replace(/Rahmen \d+/, `Rahmen ${number}`));
			});
			row.querySelector("[data-remove-box]").setAttribute("aria-label", `Rahmen ${number} entfernen`);
		});
	};

	const badge = (text) => {
		const label = document.createElement("span");

		label.textContent = text;

		return label;
	};

	// Everything on the layer comes from the fields: the band from the top-share field, one
	// rectangle per usable row. The row that has the focus is marked on the picture.
	const redrawSection = (section) => {
		const size = pictureSize(section);
		const layer = layerOf(section);

		if (layer === null || size === null) {
			return;
		}

		const rows = Array.from(containerOf(section).querySelectorAll(".privacy-box-row"));
		const focused = rows.find((row) => row.contains(document.activeElement));
		const share = currentShare(section);
		const shapes = [];

		if (share > 0 && share < 0.5) {
			const band = document.createElement("div");

			band.className = "privacy-top-band";
			band.style.height = `${share * 100}%`;
			band.append(badge("Oben: wird ignoriert"));
			shapes.push(band);
		}

		// The strip's handle lies UNDER the boxes, so where they overlap the box is grabbed (a finger is not
		// precise). At 0 it waits at the top so the strip can be pulled out of nothing; shown only while editing.
		const handle = document.createElement("div");

		handle.className = "privacy-top-handle";
		handle.style.top = `max(8px, ${share * 100}%)`;
		handle.append(badge("Oberer Rand dieser Kamera"));
		shapes.push(handle);

		rows.forEach((row, index) => {
			const box = boxOfRow(row);

			if (box === null) {
				return;
			}

			const shape = document.createElement("div");

			shape.className = row === focused ? "privacy-box-shape is-active" : "privacy-box-shape";
			shape.style.left = percent(box.x0, size.width);
			shape.style.top = percent(box.y0, size.height);
			shape.style.width = percent(box.x1 - box.x0, size.width);
			shape.style.height = percent(box.y1 - box.y0, size.height);
			shape.dataset.row = String(index);
			shape.append(badge(String(index + 1)));
			shapes.push(shape);
		});

		layer.replaceChildren(...shapes);
	};

	const refreshContainer = (container) => {
		numberRows(container);
		// The note under the heading is there exactly while no row is.
		container.closest(".privacy-boxes-field").querySelector(".privacy-boxes-empty").hidden =
			container.querySelector(".privacy-box-row") !== null;
		redrawSection(sectionOf(container));
	};

	const refreshAll = () => {
		form.querySelectorAll(".privacy-boxes").forEach(refreshContainer);
	};

	// A drawn rectangle becomes a row: the first blank one, or a new one.
	const placeBox = (container, cells) => {
		const rows = Array.from(container.querySelectorAll(".privacy-box-row"));
		let row = rows.find((candidate) =>
			cellsOf(candidate).every((input) => input.value.trim() === ""),
		);

		if (row === undefined) {
			addBoxRow(container, cells.map(String));
			row = container.lastElementChild;
		} else {
			fillRow(row, cells);
		}

		refreshContainer(container);

		return Array.from(container.querySelectorAll(".privacy-box-row")).indexOf(row) + 1;
	};

	// Gestures run only while editing is on (is-drawing), so the picture never blocks scrolling. A drag
	// on a box moves it, anywhere else draws a new one.
	const enableDrawing = (section, layer) => {
		const status = section.querySelector("[data-preview-status]");
		let gesture = null;

		const pointAt = (event) => {
			const bounds = layer.getBoundingClientRect();

			return {
				x: Math.min(Math.max(event.clientX - bounds.left, 0), bounds.width),
				y: Math.min(Math.max(event.clientY - bounds.top, 0), bounds.height),
				width: bounds.width,
				height: bounds.height,
			};
		};

		const stop = () => {
			gesture?.draft?.remove();
			gesture = null;
		};

		// The box at its new place: moved by the drag, exactly as big as before, inside the picture.
		const movedBox = (box, now, size) => {
			const width = box.x1 - box.x0;
			const height = box.y1 - box.y0;
			const x0 = Math.round(box.x0 + ((now.x - gesture.start.x) * size.width) / now.width);
			const y0 = Math.round(box.y0 + ((now.y - gesture.start.y) * size.height) / now.height);
			const left = Math.min(Math.max(x0, 0), Math.max(size.width - width, 0));
			const top = Math.min(Math.max(y0, 0), Math.max(size.height - height, 0));

			return { x0: left, y0: top, x1: left + width, y1: top + height };
		};

		// The rectangle of a drag in picture pixels, or null if it is too small to be meant or empty once
		// rounded.
		const drawnCells = (start, end, size) => {
			const left = Math.min(start.x, end.x);
			const right = Math.max(start.x, end.x);
			const top = Math.min(start.y, end.y);
			const bottom = Math.max(start.y, end.y);

			if (right - left < MIN_DRAWN_SIDE || bottom - top < MIN_DRAWN_SIDE) {
				return null;
			}

			const scaleX = size.width / end.width;
			const scaleY = size.height / end.height;
			const cells = [left * scaleX, top * scaleY, right * scaleX, bottom * scaleY].map(Math.round);

			return cells[2] > cells[0] && cells[3] > cells[1] ? cells : null;
		};

		layer.addEventListener("pointerdown", (event) => {
			if (!layer.classList.contains("is-drawing") || event.button !== 0) {
				return;
			}

			// One gesture at a time: a second finger must not take it over. The same pointer starting
			// again means its last gesture ended without a pointerup, so that one is dropped.
			if (gesture !== null) {
				if (event.pointerId !== gesture.pointerId) {
					return;
				}

				stop();
			}

			event.preventDefault();
			layer.setPointerCapture(event.pointerId);

			const start = pointAt(event);

			// The strip's edge: the drag changes this camera's top share, not a box.
			if (event.target.closest(".privacy-top-handle") !== null) {
				gesture = { kind: "strip", pointerId: event.pointerId, start, share: currentShare(section), moved: false };

				return;
			}

			const grabbed = event.target.closest(".privacy-box-shape[data-row]");
			const row = grabbed === null
				? undefined
				: containerOf(section).querySelectorAll(".privacy-box-row")[Number(grabbed.dataset.row)];
			const box = row === undefined ? null : boxOfRow(row);

			if (box !== null) {
				grabbed.classList.add("is-active");
				gesture = { kind: "move", pointerId: event.pointerId, start, box, row, shape: grabbed };

				return;
			}

			const draft = document.createElement("div");

			draft.className = "privacy-box-shape is-draft";
			layer.append(draft);
			gesture = { kind: "draw", pointerId: event.pointerId, start, draft };
		});

		layer.addEventListener("pointermove", (event) => {
			if (gesture === null || event.pointerId !== gesture.pointerId) {
				return;
			}

			const now = pointAt(event);
			const size = pictureSize(section);

			// The pointer's way down the picture, as a share of its height, from where the edge was.
			if (gesture.kind === "strip") {
				const share = gesture.share + (now.y - gesture.start.y) / now.height;

				gesture.moved = true;
				setTopShare(section, Math.min(Math.max(Math.round(share * 100) / 100, 0), Number(topFieldOf(section).max)));

				return;
			}

			// The box follows the pointer on the picture; the row's numbers change when it is let go.
			if (gesture.kind === "move") {
				const to = movedBox(gesture.box, now, size);

				gesture.shape.style.left = percent(to.x0, size.width);
				gesture.shape.style.top = percent(to.y0, size.height);

				return;
			}

			const { start, draft } = gesture;

			draft.style.left = percent(Math.min(start.x, now.x), now.width);
			draft.style.top = percent(Math.min(start.y, now.y), now.height);
			draft.style.width = percent(Math.abs(now.x - start.x), now.width);
			draft.style.height = percent(Math.abs(now.y - start.y), now.height);
		});

		layer.addEventListener("pointerup", (event) => {
			if (gesture === null || event.pointerId !== gesture.pointerId) {
				return;
			}

			const { kind, start, box, row } = gesture;

			if (kind === "strip") {
				const moved = gesture.moved;

				stop();

				if (moved) {
					status.textContent = `Oberer Rand: ${currentShare(section).toLocaleString("de-DE")} der Bildhöhe, nur für diese Kamera. Zum Übernehmen unten auf „Speichern“ drücken.`;
				}

				redrawSection(section);

				return;
			}

			const end = pointAt(event);
			const size = pictureSize(section);
			const container = containerOf(section);

			if (kind === "move" && size !== null) {
				const to = movedBox(box, end, size);

				stop();

				// A tap on a box changes nothing, however much it jitters: on a phone one screen pixel is
				// several picture pixels. Nor does a slip of less than one picture pixel.
				const dragged = Math.hypot(end.x - start.x, end.y - start.y) >= MIN_DRAWN_SIDE;

				if (dragged && (to.x0 !== box.x0 || to.y0 !== box.y0)) {
					const cells = [to.x0, to.y0, to.x1, to.y1];

					fillRow(row, cells);

					const number = Array.from(container.querySelectorAll(".privacy-box-row")).indexOf(row) + 1;

					status.textContent = `Rahmen ${number} wurde verschoben. Zum Übernehmen unten auf „Speichern“ drücken.`;
				}

				refreshContainer(container);

				return;
			}

			stop();

			const cells = size === null ? null : drawnCells(start, end, size);

			// A click, a slip or a rectangle with no area once rounded draws nothing.
			if (cells === null) {
				redrawSection(section);

				return;
			}

			const number = placeBox(container, cells);

			status.textContent = `Rahmen ${number} ist dazugekommen. Zum Übernehmen unten auf „Speichern“ drücken.`;
		});

		layer.addEventListener("pointercancel", (event) => {
			if (gesture !== null && event.pointerId !== gesture.pointerId) {
				return;
			}

			// A cancelled drag of the strip leaves the value as it was before the drag.
			if (gesture?.kind === "strip") {
				setTopShare(section, gesture.share);
			}

			stop();
			redrawSection(section);
		});
	};

	// The layer is made when the picture is there, and only once.
	const layerOf = (section) => {
		const stage = section.querySelector(".privacy-preview-stage");

		if (stage === null) {
			return null;
		}

		let layer = stage.querySelector(".privacy-preview-layer");

		if (layer === null) {
			layer = document.createElement("div");
			layer.className = "privacy-preview-layer";
			// Decoration for the mouse: the rows are the control that works for everyone.
			layer.setAttribute("aria-hidden", "true");
			stage.append(layer);
			enableDrawing(section, layer);
		}

		return layer;
	};

	// Shows the drawing tools for a camera that has a picture, and hides them for one without.
	const prepareSection = (section) => {
		const hasPicture = section.querySelector(".privacy-preview-stage") !== null;

		section.querySelector("[data-preview-draw]").hidden = !hasPicture;
		section.querySelector("[data-draw-help]").hidden = !hasPicture;

		if (hasPicture) {
			refreshContainer(containerOf(section));
		}
	};

	form.querySelectorAll("[data-preview-draw]").forEach((button) => {
		const section = button.closest("[data-preview-camera]");
		const status = section.querySelector("[data-preview-status]");

		button.addEventListener("click", () => {
			const layer = layerOf(section);

			if (layer === null) {
				return;
			}

			const drawing = button.getAttribute("aria-pressed") !== "true";

			button.setAttribute("aria-pressed", String(drawing));
			layer.classList.toggle("is-drawing", drawing);
			status.textContent = drawing
				? "Bearbeiten ist an. Ziehe ein Rechteck über das Bild oder schiebe einen Rahmen."
				: "Bearbeiten ist aus.";
		});
	});

	// The picture follows the fields while they are typed in, and the focused row lights up.
	form.addEventListener("input", (event) => {
		const container = event.target.closest(".privacy-boxes");
		const fieldset = event.target.closest(".privacy-camera");
		// The slider moves the number field without an event of its own.
		const isTopControl =
			event.target.name?.startsWith("privacy[top][") === true ||
			event.target.dataset.sliderFor?.startsWith("privacy-top-") === true;

		if (isTopControl && fieldset !== null) {
			redrawSection(fieldset.querySelector("[data-preview-camera]"));
		} else if (container !== null) {
			refreshContainer(container);
		}
	});
	// The focused row lights up on the picture. The focus is still on the old field while focusout
	// runs, so both events look a moment later, when it has moved.
	["focusin", "focusout"].forEach((name) => {
		form.addEventListener(name, (event) => {
			const container = event.target.closest(".privacy-boxes");

			if (container !== null) {
				setTimeout(() => refreshContainer(container), 0);
			}
		});
	});

	// The picture of a camera, from what the server answered. Built with the DOM and filled with
	// textContent: the answer is shown as text, never as markup.
	const showPicture = (section, picture) => {
		let figure = section.querySelector("figure");

		if (figure === null) {
			const stage = document.createElement("div");

			stage.className = "privacy-preview-stage";
			stage.append(document.createElement("img"));
			figure = document.createElement("figure");
			figure.className = "privacy-preview-figure";
			figure.append(stage, document.createElement("figcaption"));
			section.querySelector(".privacy-preview-empty")?.remove();
			section.querySelector(".privacy-help").after(figure);
		}

		const image = figure.querySelector("img");

		image.src = picture.url;
		image.width = picture.width;
		image.height = picture.height;
		image.alt = picture.alt;
		figure.querySelector("figcaption").textContent = picture.caption;

		prepareSection(section);
	};

	form.querySelectorAll("[data-preview-camera]").forEach(prepareSection);
	refreshAll();

	// "Vorschau aktualisieren" sends only the form's token, no values: it saves nothing and unsaved
	// changes stay. Hidden without JavaScript, because it would do nothing.
	const token = form.querySelector('input[name="csrf_token"]').value;

	form.querySelectorAll("[data-preview-refresh]").forEach((button) => {
		const section = button.closest("[data-preview-camera]");
		const status = section.querySelector("[data-preview-status]");

		button.hidden = false;
		button.addEventListener("click", async () => {
			button.disabled = true;
			status.textContent = "Das Bild wird geholt. Das dauert einen Moment …";

			try {
				const response = await fetch("/preview-refresh.php", {
					method: "POST",
					headers: { Accept: "application/json" },
					body: new URLSearchParams({
						csrf_token: token,
						camera: section.dataset.previewCamera,
					}),
				});
				const reply = await response.json();

				if (reply.status === "ok") {
					showPicture(section, reply.picture);
				}

				status.textContent = reply.message;
			} catch {
				status.textContent = "Das Bild konnte nicht geholt werden. Bitte später noch einmal versuchen.";
			} finally {
				button.disabled = false;
			}
		});
	});

	// What the dialog lists: everything that differs from what the page loaded with.
	const boxesText = (container) =>
		JSON.stringify(
			Array.from(container.querySelectorAll(".privacy-box-row"))
				.map((row) =>
					cellsOf(row).map((input) => input.value.trim()),
				)
				.filter((cells) => cells.some((cell) => cell !== "")),
		);
	const initial = new Map();

	form.querySelectorAll('input[name="blur_cameras[]"]').forEach((box) => {
		initial.set(box, box.checked);
	});
	form.querySelectorAll('input[type="number"][id]').forEach((input) => {
		initial.set(input, input.value);
	});
	form.querySelectorAll(".privacy-boxes").forEach((container) => {
		initial.set(container, boxesText(container));
	});

	// The rows the page loaded, so "Änderungen verwerfen" can bring them back: the browser's reset
	// blanks rows a script added and cannot restore rows that were removed.
	const loadedBoxes = new Map();

	form.querySelectorAll(".privacy-boxes").forEach((container) => {
		loadedBoxes.set(
			container,
			Array.from(container.querySelectorAll(".privacy-box-row")).map((row) => cellsOf(row).map((input) => input.value)),
		);
	});

	const describeChanges = () => {
		const changes = [];
		const cameraChanges = [];

		initial.forEach((before, element) => {
			if (element.matches('input[type="checkbox"]')) {
				if (element.checked !== before) {
					const live = element.dataset.live === "1" ? " (läuft schon!)" : "";

					cameraChanges.push(
						element.checked
							? `${element.value}: wird ab der nächsten Nacht verpixelt`
							: `${element.value}: wird NICHT mehr verpixelt${live}`,
					);
				}
			} else if (element.matches(".privacy-boxes")) {
				if (boxesText(element) !== before) {
					changes.push(`${element.dataset.label}: Rahmen geändert`);
				}
			} else if (element.value !== before) {
				const label = form.querySelector(`label[for="${element.id}"]`).textContent.trim();
				const camera = element.closest(".privacy-camera")?.dataset.camera;

				changes.push(`${camera === undefined ? "" : `Kamera ${camera}: `}${label} ${before} → ${element.value}`);
			}
		});

		return { changes, cameraChanges };
	};

	const showLines = (list, lines) => {
		list.replaceChildren(
			...lines.map((line) => {
				const item = document.createElement("li");

				item.textContent = line;

				return item;
			}),
		);
	};

	// Every submit is held back for the dialog; its "Ja, speichern" is the only way to send the form.
	form.addEventListener("submit", (event) => {
		event.preventDefault();

		const { changes, cameraChanges } = describeChanges();
		const important = dialog.querySelector("#privacy-confirm-important");

		important.hidden = cameraChanges.length === 0;
		showLines(important.querySelector("ul"), cameraChanges);
		showLines(
			dialog.querySelector("#privacy-confirm-changes"),
			changes.length === 0 && cameraChanges.length === 0
				? ["Es gibt keine Änderungen."]
				: changes,
		);
		dialog.showModal();
	});

	dialog.querySelector("[data-confirm-cancel]").addEventListener("click", () => {
		dialog.close();
	});
	dialog.querySelector("[data-confirm-yes]").addEventListener("click", () => {
		const field = document.createElement("input");

		field.type = "hidden";
		field.name = "confirm_privacy";
		field.value = "yes";
		form.append(field);
		dialog.close();
		form.submit();
	});

	// Last, so a missing shared file leaves the dialog wired: the slider, the restore buttons and
	// "Änderungen verwerfen" come from settings-common.js; this page adds what it keeps besides fields.
	SettingsForm.init(form, {
		// The Standard box rows of a camera replace the rows that stand there now.
		onRestore: (scope) => {
			scope.querySelectorAll("[data-default-boxes]").forEach((container) => {
				container.replaceChildren();
				JSON.parse(container.dataset.defaultBoxes).forEach((box) => {
					addBoxRow(container, box.map(String));
				});
			});

			// The rows and the top-share field changed without an event the picture listens to.
			refreshAll();
		},
		// The rows are rebuilt from what the page loaded, and the pictures drawn again from them.
		onReset: () => {
			loadedBoxes.forEach((boxes, container) => {
				container.replaceChildren();
				boxes.forEach((cells) => addBoxRow(container, cells));
			});
			refreshAll();
		},
	});
})();
