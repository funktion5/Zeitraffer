<?php

declare(strict_types=1);

require_once __DIR__ . "/../src/video-library.php";
$cameras = findAvailableCameras();
$storage = getStorageUsage();
?>

<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
	<link rel="stylesheet" href="/style.css">
  <title>Document</title>
</head>
<body>
	<header>
		
			<?php require __DIR__ . "/../src/components/header.php"; ?>
	
	</header>
	<h1>Available cameras</h1>
	
	<section>

		<?php if ($cameras === []): ?>
			<p>No cameras found.</p>
			<?php else: ?>
				<ul>
					<?php foreach ($cameras as $camera): ?>
						<li>
							<a href="/camera.php?camera=<?= rawurlencode($camera) ?>">
									<?= htmlspecialchars($camera, ENT_QUOTES, "UTF-8") ?>
							</a>
						</li>
						<?php endforeach; ?>
					</ul>
					<?php endif; ?>
		</section>
</body>
</html>