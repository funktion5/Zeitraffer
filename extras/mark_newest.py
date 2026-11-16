"""Optional extra: mark the newest image of every camera that is not blurred (extras/README.md).

The website's pick-up script publishes only images that carry the checked mark. Blur cameras get it
from the blur round; every other camera is cleared for the website by default, so its newest image
gets the same mark without being looked at. Connected to nothing: it runs only when someone appends
it to the live round's cron line.
"""

from datetime import datetime

from src.images import image_moment


# The same choice as the pick-up script: the newest by the time in its name, skipping empty files.
# A name without a readable time cannot be placed and is never chosen.
def newest_image(images: dict[str, int], timezone: str) -> str | None:
	candidates: list[tuple[datetime, str]] = []

	for name, size in images.items():
		moment = image_moment(name, timezone)

		if size > 0 and moment is not None:
			candidates.append((moment, name))

	return max(candidates)[1] if candidates else None
