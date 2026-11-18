<?php

declare(strict_types=1);

// Always visible below the header: what needs someone, or that nothing does (warnings.php).
$banner = bannerMessages($bannerNow ?? bannerNow(), $storage ?? null);
$bannerCount = count($banner["messages"]);
$bannerTitle = match ($bannerCount) {
	0 => "Nichts zu melden.",
	1 => "1 Meldung",
	default => $bannerCount . " Meldungen",
};
?>
<div class="warning-banner" data-state="<?= $bannerCount > 0 ? "warn" : "ok" ?>" role="status">
	<p class="warning-banner-title">
		<span class="warning-banner-icon" aria-hidden="true"><?= $bannerCount > 0 ? "⚠" : "✓" ?></span>
		<?= htmlspecialchars($bannerTitle, ENT_QUOTES, "UTF-8") ?>
	</p>

	<?php if ($bannerCount > 0): ?>
		<ul class="warning-banner-list">
			<?php foreach ($banner["messages"] as $message): ?>
				<li>
					<?php if ($message["camera"] !== null): ?>
						<strong><?= htmlspecialchars($message["camera"], ENT_QUOTES, "UTF-8") ?>:</strong>
					<?php endif; ?>
					<?= htmlspecialchars($message["text"], ENT_QUOTES, "UTF-8") ?>
					<span class="warning-banner-hint"><span aria-hidden="true">→</span> <?= htmlspecialchars($message["hint"], ENT_QUOTES, "UTF-8") ?></span>
				</li>
			<?php endforeach; ?>
		</ul>
	<?php endif; ?>

	<?php if ($banner["lastRun"] !== null): ?>
		<p class="warning-banner-run">Letzter Nachtlauf: <?= htmlspecialchars($banner["lastRun"], ENT_QUOTES, "UTF-8") ?></p>
	<?php endif; ?>
</div>
