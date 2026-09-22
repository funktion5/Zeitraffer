from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from src.images import extract_date


CoverageType = Literal[
	"monthly",
	"yearly",
]


COVERAGE_DAYS = {
	"monthly": 30,
	"yearly": 365,
}


def get_coverage_date_range(
	end_date: date,
	coverage_type: CoverageType,
) -> tuple[date, date]:
	days = COVERAGE_DAYS[coverage_type]

	start_date = end_date - timedelta(days=days - 1)

	return (
		start_date,
		end_date,
	)


def get_missing_dates(
	images: list[Path],
	start_date: date,
	end_date: date,
) -> list[date]:
	available_dates = {
		image_date
		for image_path in images
		if (image_date := extract_date(image_path.name)) is not None
	}

	return [
		start_date + timedelta(days=offset)
		for offset in range((end_date - start_date).days + 1)
		if start_date + timedelta(days=offset) not in available_dates
	]
