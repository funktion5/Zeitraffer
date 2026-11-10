<?php

declare(strict_types=1);

// The tabs of the settings area: two real pages, each with its own form and its own save button. The
// page sets $currentTab ("general" or "verpixelung") to mark its own tab.

?>
<nav class="settings-tabs" aria-label="Bereiche der Einstellungen">
	<a href="/settings.php"<?= ($currentTab ?? "") === "general" ? ' aria-current="page"' : "" ?>>Allgemein</a>
	<a href="/verpixelung.php"<?= ($currentTab ?? "") === "verpixelung" ? ' aria-current="page"' : "" ?>>Verpixelung</a>
</nav>
