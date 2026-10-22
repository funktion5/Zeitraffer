import pytest

from src.config import load_config
from src.flagger.settings import FlaggerSettings, load_flagger_settings


def test_missing_section_means_no_cameras():
	assert load_flagger_settings({}) == FlaggerSettings(cameras=(), retention_days=30)


def test_reads_cameras_and_retention_and_collapses_duplicates():
	config = {"flagger": {"cameras": ["B", "A", "B"], "retention_days": 14}}

	assert load_flagger_settings(config) == FlaggerSettings(cameras=("B", "A"), retention_days=14)


def test_rejects_retention_below_a_week():
	with pytest.raises(ValueError, match="retention_days"):
		load_flagger_settings({"flagger": {"cameras": [], "retention_days": 6}})


@pytest.mark.parametrize("retention_days", ["30", 30.0, True, None])
def test_rejects_retention_that_is_not_an_integer(retention_days):
	with pytest.raises(ValueError, match="retention_days"):
		load_flagger_settings({"flagger": {"cameras": [], "retention_days": retention_days}})


@pytest.mark.parametrize("cameras", ["SLSV", ["SLSV", 3], None])
def test_rejects_malformed_camera_list(cameras):
	with pytest.raises(ValueError, match="cameras"):
		load_flagger_settings({"flagger": {"cameras": cameras}})


def test_repo_config_flags_no_ignored_camera():
	# An ignored camera in flagger.cameras makes require_cameras refuse the whole run.
	config = load_config()
	settings = load_flagger_settings(config)

	assert not set(settings.cameras) & set(config["ignored_cameras"])
