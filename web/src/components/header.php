<?php

declare(strict_types=1);

?>

<header class="main-header">
	<nav aria-label="Main navigation">
		<a href="/">Cameras</a>
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

			<dl aria-label="Storage usage">
				<div>
					<dt>Total</dt>
					<dd>
						<?= htmlspecialchars(
							$storage["total"],
							ENT_QUOTES,
							"UTF-8",
						) ?>
					</dd>
				</div>

				<div>
					<dt>Used</dt>
					<dd>
						<?= htmlspecialchars(
							$storage["used"],
							ENT_QUOTES,
							"UTF-8",
						) ?>
					</dd>
				</div>

				<div>
					<dt>Available</dt>
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