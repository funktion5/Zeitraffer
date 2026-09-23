<?php

declare(strict_types=1);

require_once __DIR__ . "/../src/video-library.php";
$cameras = findAvailableCameras();
?>

<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Document</title>
</head>
<body>
	<h1>Available cameras</h1>
	

	<?php if ($cameras === []): ?>
		<p>No cameras found.</p>
	<?php else: ?>
		<ul>
			<?php foreach ($cameras as $camera): ?>
				<li>
					<?= htmlspecialchars($camera, ENT_QUOTES, "UTF-8") ?>
				</li>
			<?php endforeach; ?>
		</ul>
	<?php endif; ?>
</body>
</html>