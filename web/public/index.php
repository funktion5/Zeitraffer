<?php

declare(strict_types=1);

require_once __DIR__ . "/../src/video-library.php";
$cameras = findAvailableCameras();
$storage = getStorageUsage();
?>

<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
	<link rel="stylesheet" href="/style.css">
  <title>Kameras – Zeitraffer</title>
</head>
<body>
	<header>

			<?php require __DIR__ . "/../src/components/header.php"; ?>

	</header>
	<h1>Verfügbare Kameras</h1>

	<section>

		<?php if ($cameras === []): ?>
			<p>Keine Kameras gefunden.</p>
			<?php else: ?>
				<ul>
					<?php foreach ($cameras as $cameraName): ?>
						<li>
							<a href="/camera.php?camera=<?= rawurlencode($cameraName) ?>">
									<?= htmlspecialchars($cameraName, ENT_QUOTES, "UTF-8") ?>
							</a>
						</li>
						<?php endforeach; ?>
					</ul>
					<?php endif; ?>
		</section>

	<?php require __DIR__ . "/../src/components/job-watcher.php"; ?>
</body>
</html>