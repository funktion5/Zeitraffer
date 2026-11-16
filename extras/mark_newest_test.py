from extras.mark_newest import newest_image

TIMEZONE = "Europe/Berlin"


# The same image as the website's pick-up script: the newest by the time in its name, not by listing
# order, and never an empty file.
def test_the_newest_image_by_its_name_is_chosen() -> None:
	images = {
		"20261116T121000.jpg": 200_000,
		"20261116T122000.jpg": 210_000,
		"20261115T235000.jpg": 190_000,
	}

	assert newest_image(images, TIMEZONE) == "20261116T122000.jpg"


def test_yesterdays_last_image_counts_when_today_has_none() -> None:
	images = {"20261115T235000.jpg": 190_000, "20261115T234000.jpg": 180_000}

	assert newest_image(images, TIMEZONE) == "20261115T235000.jpg"


# An empty upload is skipped by the pick-up script, which then takes the one before.
def test_an_empty_newest_image_falls_back_to_the_one_before() -> None:
	images = {"20261116T122000.jpg": 0, "20261116T121000.jpg": 200_000}

	assert newest_image(images, TIMEZONE) == "20261116T121000.jpg"


def test_no_image_or_only_empty_ones_gives_none() -> None:
	assert newest_image({}, TIMEZONE) is None
	assert newest_image({"20261116T122000.jpg": 0}, TIMEZONE) is None


# Without a readable time it cannot be placed, so it is never taken for the newest.
def test_a_name_without_a_readable_time_is_never_chosen() -> None:
	images = {"cam-latest.jpg": 200_000, "20261116T121000.jpg": 200_000}

	assert newest_image(images, TIMEZONE) == "20261116T121000.jpg"
