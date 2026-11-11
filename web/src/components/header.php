<?php

declare(strict_types=1);

?>

<header class="main-header">
	<nav aria-label="Hauptnavigation">
		<a href="/">Kameras</a>
		<a href="/highlights.php">Highlights</a>
	</nav>

	<?php if ($storage !== null): ?>
		<?php
		// The ring is five arcs of one circle drawn with pathLength 100, so a dash length is a percent.
		// Each arc has a tooltip box that the CSS shows while that arc is hovered (the browser's own
		// title tooltip only appears after a delay). Empty parts are left out. An unknown level
		// counts as "ok".
		$parts = array_column($storage["segments"], null, "key");
		$names = [
			"automatic" => "Automatische Videos",
			"manual" => "Manuelle Videos",
			"highlights" => "Highlight-Bilder",
			"other" => "Sonstiges (System, Modelle, Logs)",
			"free" => "Frei",
		];
		$arcs = [];
		$start = 0.0;

		foreach ($names as $key => $name) {
			$percent = (float) $parts[$key]["percent"];
			$label = $name . ": " . formatBytes($parts[$key]["bytes"]) . " (" . number_format($percent, 1) . " %)";

			if ($percent > 0) {
				$arcs[] = ["key" => $key, "label" => $label, "start" => round($start, 1), "percent" => $percent];
			}

			$start += $percent;
		}

		$summary = implode("; ", array_column($arcs, "label"));
		$level = in_array($storage["level"], ["warn", "critical"], true) ? $storage["level"] : "ok";
		$warning = ["warn" => "Speicher wird knapp", "critical" => "Speicher fast voll"][$level] ?? null;
		?>
		<div class="storage-overview" data-level="<?= $level ?>">
			<div class="storage-chart">
				<svg viewBox="0 0 72 72" role="img" aria-label="<?= htmlspecialchars($summary, ENT_QUOTES, "UTF-8") ?>">
					<g transform="rotate(-90 36 36)">
						<?php foreach ($arcs as $arc): ?>
							<circle
								class="storage-arc storage-arc-<?= $arc["key"] ?>"
								cx="36" cy="36" r="31" pathLength="100"
								stroke-dasharray="<?= $arc["percent"] ?> <?= round(100 - $arc["percent"], 1) ?>"
								stroke-dashoffset="<?= $arc["start"] > 0 ? -$arc["start"] : 0 ?>"
							/>
						<?php endforeach; ?>
					</g>
				</svg>
				<?php foreach ($arcs as $arc): ?>
					<span class="storage-tip storage-tip-<?= $arc["key"] ?>" aria-hidden="true"><?= htmlspecialchars($arc["label"], ENT_QUOTES, "UTF-8") ?></span>
				<?php endforeach; ?>
				<span class="storage-percent">
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

				<div>
					<dt>Davon Videos</dt>
					<dd>
						<?= htmlspecialchars(
							$storage["videos"],
							ENT_QUOTES,
							"UTF-8",
						) ?>
					</dd>
				</div>
			</dl>

			<?php if ($warning !== null): ?>
				<p class="storage-warning"><?= $warning ?></p>
			<?php endif; ?>
		</div>
	<?php endif; ?>

	<?php // At the far right, after the storage overview; the page sets $currentPage to mark its link. ?>
	<nav class="settings-nav" aria-label="Einstellungen">
		<a class="settings-link" href="/settings.php"<?= ($currentPage ?? "") === "settings" ? ' aria-current="page"' : "" ?>>
			<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
				<path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58a.49.49 0 0 0 .12-.61l-1.92-3.32a.488.488 0 0 0-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54a.484.484 0 0 0-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58a.49.49 0 0 0-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z" />
			</svg>
			<span>Einstellungen</span>
		</a>
	</nav>
</header>

<!-- A running job, announced at the very top of every page; job-watcher.php fills and hides it. -->
<p id="job-live-status" role="status" aria-live="polite" hidden></p>