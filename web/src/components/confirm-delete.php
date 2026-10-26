<?php

declare(strict_types=1);

// Shared confirm step for every form marked data-delete-confirm (camera.php, highlights.php);
// the form's data-delete-name names the file in the question. The page sets
// $deleteDialogTitle before including this after its forms. On confirm it deletes in the
// background and fires "deleted" on the form; the page decides what to update.

?>

<!-- Background deletes change the page silently; this tells screen readers what happened. -->
<p id="delete-status" class="visually-hidden" role="status"></p>

<dialog id="confirm-delete-dialog">
	<h2 id="confirm-delete-title"><?= htmlspecialchars($deleteDialogTitle, ENT_QUOTES, "UTF-8") ?></h2>
	<p id="confirm-delete-message"></p>

	<form method="dialog">
		<button type="submit">Abbrechen</button>
		<button type="button" id="confirm-delete-button">Löschen</button>
	</form>
</dialog>

<script>
	(function () {
		const deleteDialog = document.querySelector("#confirm-delete-dialog");
		const deleteDialogMessage = document.querySelector("#confirm-delete-message");
		const deleteDialogConfirmButton = document.querySelector("#confirm-delete-button");
		const deleteStatus = document.querySelector("#delete-status");
		let pendingDeleteForm = null;

		function buildDeleteConfirmMessage(name) {
			return `„${name}“ wirklich löschen? Dies kann nicht rückgängig gemacht werden.`;
		}

		// Require an explicit confirm click before any delete form is submitted. Falls back to
		// window.confirm() and a normal page post where <dialog>.showModal is unavailable.
		document.querySelectorAll("form[data-delete-confirm]").forEach((form) => {
			form.addEventListener("submit", (event) => {
				event.preventDefault();

				if (typeof deleteDialog.showModal !== "function") {
					if (window.confirm(buildDeleteConfirmMessage(form.dataset.deleteName))) {
						form.submit();
					}

					return;
				}

				pendingDeleteForm = form;
				deleteDialogMessage.textContent = buildDeleteConfirmMessage(form.dataset.deleteName);
				deleteDialogConfirmButton.hidden = false;
				deleteDialogConfirmButton.disabled = false;
				deleteDialog.showModal();
			});
		});

		// Delete in the background so the page keeps its state (open lists, the image viewer):
		// the form then fires "deleted" and the page updates itself. A refusal or a lost
		// connection stays in the dialog; "Abbrechen" closes it.
		deleteDialogConfirmButton.addEventListener("click", async () => {
			const form = pendingDeleteForm;

			if (form === null) {
				return;
			}

			deleteDialogConfirmButton.disabled = true;
			const body = new FormData(form);
			body.append("response", "json");
			let result;

			try {
				// getAttribute: camera.php's forms have an input named "action", which form.action
				// would return instead of the URL.
				const response = await fetch(form.getAttribute("action"), { method: "POST", body });
				result = await response.json();
			} catch (error) {
				result = {
					deleted: false,
					message: "Das Löschen hat nicht geklappt. Bitte die Seite neu laden.",
				};
			}

			if (!result.deleted) {
				deleteDialogMessage.textContent = result.message;
				deleteDialogConfirmButton.hidden = true;
				return;
			}

			pendingDeleteForm = null;
			deleteDialog.close();
			deleteStatus.textContent = `${result.message} (${form.dataset.deleteName})`;
			form.dispatchEvent(new CustomEvent("deleted", { bubbles: true }));
		});
	})();
</script>
