<?php

declare(strict_types=1);

// The settings pages' "bigger header": two colourful donuts, the whole disk and the videos only, and
// a list saying what each part is. Needs $storage (getStorageUsage()) from the page; the tooltip
// of each arc is shown by storage-ring.js.

?>
<?php if ($storage !== null): ?>
	<?php
	$esc = static fn(string $text): string => htmlspecialchars($text, ENT_QUOTES, "UTF-8");
	$parts = storageCameraParts($storage["segments"], getVideoStorage());
	$videoParts = storageVideoParts($parts);

	$donuts = [
		[
			"caption" => "Der ganze Speicher",
			"value" => $storage["usedPercent"] . "%",
			"text" => "belegt",
			"arcs" => storageArcs($parts, "percent", "des Speichers"),
		],
	];

	if ($videoParts !== []) {
		$donuts[] = [
			"caption" => "Nur die Videos",
			"value" => formatBytes(array_sum(array_column($videoParts, "bytes"))),
			"text" => "Videos",
			"arcs" => storageArcs($videoParts, "videoPercent", "der Videos"),
		];
	}
	?>
	<section class="storage-panel" aria-labelledby="storage-panel-title">
		<h2 id="storage-panel-title">Speicher</h2>

		<div class="storage-donuts">
			<?php foreach ($donuts as $donut): ?>
				<figure class="storage-figure">
					<div class="storage-donut">
						<svg viewBox="0 0 72 72" role="img" aria-label="<?= $esc($donut["caption"] . ": " . implode("; ", array_column($donut["arcs"], "tip"))) ?>">
							<g transform="rotate(-90 36 36)">
								<?php foreach ($donut["arcs"] as $arc): ?>
									<circle class="storage-donut-arc" cx="36" cy="36" r="28" pathLength="100" data-tip="<?= $esc($arc["tip"]) ?>" style="stroke: <?= $arc["color"] ?>" stroke-dasharray="<?= $arc["percent"] ?> <?= round(100 - $arc["percent"], 1) ?>" stroke-dashoffset="<?= $arc["start"] > 0 ? -$arc["start"] : 0 ?>" />
								<?php endforeach; ?>
							</g>
						</svg>
						<span class="storage-donut-middle"><strong><?= $esc($donut["value"]) ?></strong> <?= $donut["text"] ?></span>
					</div>
					<figcaption><?= $donut["caption"] ?></figcaption>
				</figure>
			<?php endforeach; ?>
		</div>

		<ul class="storage-parts">
			<?php foreach ($parts as $part): ?>
				<li>
					<span class="storage-part-swatch" style="background: <?= $part["color"] ?>" aria-hidden="true"></span>
					<span class="storage-part-name"><?= $esc($part["label"]) ?></span>
					<span class="storage-part-size"><?= $esc(formatBytes($part["bytes"])) ?></span>
				</li>
			<?php endforeach; ?>
		</ul>
	</section>
<?php endif; ?>
