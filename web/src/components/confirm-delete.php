<?php

declare(strict_types=1);

// Shared confirm step for every form marked data-delete-confirm (camera.php, highlights.php);
// the form's data-delete-name names the file in the question. The page sets
// $deleteDialogTitle before including this after its forms.

?>

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
		let pendingDeleteForm = null;

		function buildDeleteConfirmMessage(name) {
			return `„${name}“ wirklich löschen? Dies kann nicht rückgängig gemacht werden.`;
		}

		// Require an explicit confirm click before any delete form is submitted. Falls back to
		// window.confirm() where <dialog>.showModal is unavailable, so the delete action never
		// silently does nothing.
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
				deleteDialog.showModal();
			});
		});

		deleteDialogConfirmButton.addEventListener("click", () => {
			const form = pendingDeleteForm;
			pendingDeleteForm = null;

			if (form !== null) {
				form.submit();
			}
		});
	})();
</script>
