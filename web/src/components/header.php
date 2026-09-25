<?php

declare(strict_types=1);

?>

<header class="main-header">
	<nav aria-label="Hauptnavigation">
		<a href="/">Kameras</a>
	</nav>

	<?php if ($storage !== null): ?>
		<div class="storage-overview">
			<div
				class="storage-chart"
				style="--storage-used: <?= htmlspecialchars(
					(string) $storage["usedPercent"],
					ENT_QUOTES,
					"UTF-8",
				) ?>%"
			>
				<span>
					<?= htmlspecialchars(
						(string) $storage["usedPercent"],
						ENT_QUOTES,
						"UTF-8",
					) ?>%
				</span>
			</div>

			<dl aria-label="Speichernutzung">
				<div>
					<dt>Gesamt</dt>
					<dd>
						<?= htmlspecialchars(
							$storage["total"],
							ENT_QUOTES,
							"UTF-8",
						) ?>
					</dd>
				</div>

				<div>
					<dt>Belegt</dt>
					<dd>
						<?= htmlspecialchars(
							$storage["used"],
							ENT_QUOTES,
							"UTF-8",
						) ?>
					</dd>
				</div>

				<div>
					<dt>Verfügbar</dt>
					<dd>
						<?= htmlspecialchars(
							$storage["available"],
							ENT_QUOTES,
							"UTF-8",
						) ?>
					</dd>
				</div>
			</dl>
		</div>
	<?php endif; ?>
</header>