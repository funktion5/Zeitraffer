from dataclasses import dataclass

# Highlights are reviewed about once a week, so a shorter retention could delete unseen flags.
MIN_RETENTION_DAYS = 7
DEFAULT_RETENTION_DAYS = 30


@dataclass(frozen=True)
class FlaggerSettings:
	cameras: tuple[str, ...]
	retention_days: int


# Read the optional "flagger" section; a missing section means nothing is checked.
def load_flagger_settings(config: dict) -> FlaggerSettings:
	section = config.get("flagger", {})
	cameras = section.get("cameras", [])
	retention_days = section.get("retention_days", DEFAULT_RETENTION_DAYS)

	if not isinstance(cameras, list) or not all(isinstance(camera, str) for camera in cameras):
		raise ValueError(f"flagger.cameras must be a list of camera names: {cameras!r}")

	# bool is an int subclass, so true would otherwise pass as 1 day.
	if not isinstance(retention_days, int) or isinstance(retention_days, bool):
		raise ValueError(f"flagger.retention_days must be an integer: {retention_days!r}")

	if retention_days < MIN_RETENTION_DAYS:
		raise ValueError(
			f"flagger.retention_days must be at least {MIN_RETENTION_DAYS}: {retention_days}"
		)

	return FlaggerSettings(
		cameras=tuple(dict.fromkeys(cameras)),
		retention_days=retention_days,
	)
