import logging
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path

import src.jobs.manual as manual_module

TEST_CONFIG = {
	"location": {
		"latitude": 52.0,
		"longitude": 9.0,
		"timezone": "Europe/Berlin",
	},
	"daylight_buffer_minutes": 90,
	"image_scan_stall_timeout_seconds": 10,
	"timelapse": {
		"daily_framerate": 10,
		"manual_framerate": 10,
		"monthly_framerate": 20,
		"yearly_framerate": 20,
	},
}

MANUAL_FRAMERATE = TEST_CONFIG["timelapse"]["manual_framerate"]

TEST_SUNRISE = datetime(
	2026,
	9,
	16,
	7,
	0,
	tzinfo=UTC,
)

TEST_SUNSET = datetime(
	2026,
	9,
	16,
	19,
	0,
	tzinfo=UTC,
)


def mock_manual_dependencies(
	monkeypatch,
	tmp_path: Path,
) -> None:
	"""Mock dependencies shared by manual workflow tests."""

	monkeypatch.setattr(
		manual_module,
		"get_sun_times",
		lambda **kwargs: (
			TEST_SUNRISE,
			TEST_SUNSET,
		),
	)

	def fake_get_video_path(
		camera,
		target_date,
		timelapse_type,
		manual_run=False,
	):
		if manual_run:
			return (
				tmp_path
				/ "videos"
				/ camera
				/ "manual-runs"
				/ timelapse_type
				/ f"{camera}_{target_date.isoformat()}.mp4"
			)

		return (
			tmp_path
			/ "videos"
			/ camera
			/ timelapse_type
			/ f"{camera}_{target_date.isoformat()}.mp4"
		)

	monkeypatch.setattr(
		manual_module,
		"get_video_path",
		fake_get_video_path,
	)


# A manual job must create a timelapse for the supplied date.
def test_run_manual_job_creates_timelapse(
	monkeypatch,
	tmp_path,
):
	target_date = date(
		2026,
		9,
		16,
	)

	images = [
		Path("image_1.jpg"),
		Path("image_2.jpg"),
	]

	mock_manual_dependencies(
		monkeypatch,
		tmp_path,
	)

	monkeypatch.setattr(
		manual_module,
		"find_images_isolated",
		lambda **kwargs: images,
	)

	create_timelapse_calls = []

	def fake_create_timelapse(
		camera,
		target_date,
		images,
		timelapse_type,
		framerate,
		manual_run=False,
	):
		create_timelapse_calls.append(
			{
				"camera": camera,
				"target_date": target_date,
				"images": images,
				"timelapse_type": timelapse_type,
				"framerate": framerate,
				"manual_run": manual_run,
			}
		)

		return Path(f"videos/{camera}/{timelapse_type}/{camera}_{target_date.isoformat()}.mp4")

	monkeypatch.setattr(
		manual_module,
		"create_timelapse",
		fake_create_timelapse,
	)

	manual_module.run_manual_job(
		config=TEST_CONFIG,
		available_cameras=[
			"Test-Camera",
		],
		target_date=target_date,
		requested_cameras=None,
		framerate=MANUAL_FRAMERATE,
	)

	assert create_timelapse_calls == [
		{
			"camera": "Test-Camera",
			"target_date": target_date,
			"images": images,
			"timelapse_type": "manual",
			"framerate": MANUAL_FRAMERATE,
			"manual_run": True,
		}
	]


# Existing manual videos must be skipped before image selection starts.
def test_run_manual_job_skips_existing_video(
	monkeypatch,
	tmp_path,
	caplog,
):
	target_date = date(
		2026,
		9,
		16,
	)

	mock_manual_dependencies(
		monkeypatch,
		tmp_path,
	)

	existing_video = (
		tmp_path / "videos" / "Camera-A" / "manual-runs" / "manual" / "Camera-A_2026-09-16.mp4"
	)

	existing_video.parent.mkdir(
		parents=True,
		exist_ok=True,
	)

	existing_video.touch()

	find_images_isolated_called = False
	create_timelapse_called = False

	def fake_find_images_isolated(
		**kwargs,
	):
		nonlocal find_images_isolated_called
		find_images_isolated_called = True

		return [Path("image.jpg")]

	def fake_create_timelapse(
		**kwargs,
	):
		nonlocal create_timelapse_called
		create_timelapse_called = True

		return existing_video

	monkeypatch.setattr(
		manual_module,
		"find_images_isolated",
		fake_find_images_isolated,
	)

	monkeypatch.setattr(
		manual_module,
		"create_timelapse",
		fake_create_timelapse,
	)

	with caplog.at_level(
		logging.INFO,
		logger="timelapse",
	):
		manual_module.run_manual_job(
			config=TEST_CONFIG,
			available_cameras=[
				"Camera-A",
			],
			target_date=target_date,
			requested_cameras=None,
			framerate=MANUAL_FRAMERATE,
		)

	assert find_images_isolated_called is False
	assert create_timelapse_called is False

	assert "Manual video already exists - skipping camera" in caplog.text


# A manual camera filter must process only explicitly requested cameras.
def test_run_manual_job_processes_only_requested_cameras(
	monkeypatch,
	tmp_path,
):
	target_date = date(
		2026,
		9,
		16,
	)

	mock_manual_dependencies(
		monkeypatch,
		tmp_path,
	)

	processed_cameras = []

	def fake_find_images_isolated(
		camera,
		**kwargs,
	):
		processed_cameras.append(camera)

		return [Path(f"{camera}_2026-09-16.jpg")]

	monkeypatch.setattr(
		manual_module,
		"find_images_isolated",
		fake_find_images_isolated,
	)

	monkeypatch.setattr(
		manual_module,
		"create_timelapse",
		lambda **kwargs: Path(
			f"videos/{kwargs['camera']}/manual/{kwargs['camera']}_2026-09-16.mp4"
		),
	)

	manual_module.run_manual_job(
		config=TEST_CONFIG,
		available_cameras=[
			"Camera-A",
			"Camera-B",
			"Camera-C",
		],
		target_date=target_date,
		requested_cameras=[
			"Camera-B",
			"Camera-C",
		],
		framerate=MANUAL_FRAMERATE,
	)

	assert processed_cameras == [
		"Camera-B",
		"Camera-C",
	]


# Unknown requested cameras must be logged without stopping valid cameras.
def test_run_manual_job_logs_unknown_camera_and_continues(
	monkeypatch,
	tmp_path,
	caplog,
):
	target_date = date(
		2026,
		9,
		16,
	)

	mock_manual_dependencies(
		monkeypatch,
		tmp_path,
	)

	processed_cameras = []

	def fake_find_images_isolated(
		camera,
		**kwargs,
	):
		processed_cameras.append(camera)

		return [Path(f"{camera}_2026-09-16.jpg")]

	monkeypatch.setattr(
		manual_module,
		"find_images_isolated",
		fake_find_images_isolated,
	)

	monkeypatch.setattr(
		manual_module,
		"create_timelapse",
		lambda **kwargs: Path(
			f"videos/{kwargs['camera']}/manual/{kwargs['camera']}_2026-09-16.mp4"
		),
	)

	with caplog.at_level(
		logging.ERROR,
		logger="timelapse",
	):
		manual_module.run_manual_job(
			config=TEST_CONFIG,
			available_cameras=[
				"Camera-A",
				"Camera-B",
			],
			target_date=target_date,
			requested_cameras=[
				"Camera-Missing",
				"Camera-B",
			],
			framerate=MANUAL_FRAMERATE,
		)

	assert "Requested camera not found: Camera-Missing" in caplog.text

	assert processed_cameras == ["Camera-B"]


# Duplicate requested camera names must only be processed once.
def test_run_manual_job_deduplicates_requested_cameras(
	monkeypatch,
	tmp_path,
):
	target_date = date(
		2026,
		9,
		16,
	)

	mock_manual_dependencies(
		monkeypatch,
		tmp_path,
	)

	processed_cameras = []

	def fake_find_images_isolated(
		camera,
		**kwargs,
	):
		processed_cameras.append(camera)

		return [Path("image.jpg")]

	monkeypatch.setattr(
		manual_module,
		"find_images_isolated",
		fake_find_images_isolated,
	)

	monkeypatch.setattr(
		manual_module,
		"create_timelapse",
		lambda **kwargs: Path(
			f"videos/{kwargs['camera']}/manual/{kwargs['camera']}_2026-09-16.mp4"
		),
	)

	manual_module.run_manual_job(
		config=TEST_CONFIG,
		available_cameras=[
			"Camera-B",
			"Camera-C",
		],
		target_date=target_date,
		requested_cameras=[
			"Camera-B",
			"Camera-B",
			"Camera-C",
			"Camera-B",
		],
		framerate=MANUAL_FRAMERATE,
	)

	assert processed_cameras == [
		"Camera-B",
		"Camera-C",
	]


# A video failure for one camera must not stop the next camera.
def test_run_manual_job_continues_after_video_error(
	monkeypatch,
	tmp_path,
):
	target_date = date(
		2026,
		9,
		16,
	)

	images = [Path("image_1.jpg")]

	mock_manual_dependencies(
		monkeypatch,
		tmp_path,
	)

	monkeypatch.setattr(
		manual_module,
		"find_images_isolated",
		lambda **kwargs: images,
	)

	processed_cameras = []

	def fake_create_timelapse(
		camera,
		target_date,
		images,
		timelapse_type,
		framerate,
		manual_run=False,
	):
		processed_cameras.append(camera)

		if camera == "Camera-A":
			raise subprocess.CalledProcessError(
				returncode=1,
				cmd=["ffmpeg"],
			)

		return Path(f"videos/{camera}/{timelapse_type}/{camera}_{target_date.isoformat()}.mp4")

	monkeypatch.setattr(
		manual_module,
		"create_timelapse",
		fake_create_timelapse,
	)

	logged_errors = []

	def fake_logger_exception(
		message,
	):
		logged_errors.append(message)

	monkeypatch.setattr(
		manual_module.logger,
		"exception",
		fake_logger_exception,
	)

	manual_module.run_manual_job(
		config=TEST_CONFIG,
		available_cameras=[
			"Camera-A",
			"Camera-B",
		],
		target_date=target_date,
		requested_cameras=None,
		framerate=MANUAL_FRAMERATE,
	)

	assert processed_cameras == [
		"Camera-A",
		"Camera-B",
	]

	assert logged_errors == ["Failed to process timelapse for camera: Camera-A"]


# A read error for one camera must not stop later cameras.
def test_run_manual_job_continues_after_image_selection_error(
	monkeypatch,
	tmp_path,
):
	target_date = date(
		2026,
		9,
		16,
	)

	images = [Path("image_1.jpg")]

	mock_manual_dependencies(
		monkeypatch,
		tmp_path,
	)

	def fake_find_images_isolated(
		camera,
		**kwargs,
	):
		if camera == "Camera-A":
			raise OSError("Failed to read camera images")

		return images

	monkeypatch.setattr(
		manual_module,
		"find_images_isolated",
		fake_find_images_isolated,
	)

	processed_cameras = []

	def fake_create_timelapse(
		camera,
		**kwargs,
	):
		processed_cameras.append(camera)

		return Path(f"videos/{camera}/manual/video.mp4")

	monkeypatch.setattr(
		manual_module,
		"create_timelapse",
		fake_create_timelapse,
	)

	manual_module.run_manual_job(
		config=TEST_CONFIG,
		available_cameras=[
			"Camera-A",
			"Camera-B",
		],
		target_date=target_date,
		requested_cameras=None,
		framerate=MANUAL_FRAMERATE,
	)

	assert processed_cameras == ["Camera-B"]


# A stalled camera must not prevent later manual cameras from being processed.
def test_run_manual_job_continues_after_image_scan_timeout(
	monkeypatch,
	tmp_path,
):
	target_date = date(
		2026,
		9,
		16,
	)

	images = [Path("image.jpg")]

	mock_manual_dependencies(
		monkeypatch,
		tmp_path,
	)

	def fake_find_images_isolated(
		camera,
		**kwargs,
	):
		# Simulate one camera whose image scan stops making progress.
		if camera == "Camera-A":
			raise TimeoutError("Image scan stalled")

		return images

	monkeypatch.setattr(
		manual_module,
		"find_images_isolated",
		fake_find_images_isolated,
	)

	processed_cameras = []

	def fake_create_timelapse(
		camera,
		**kwargs,
	):
		processed_cameras.append(camera)

		return Path(f"videos/{camera}/manual/video.mp4")

	monkeypatch.setattr(
		manual_module,
		"create_timelapse",
		fake_create_timelapse,
	)

	manual_module.run_manual_job(
		config=TEST_CONFIG,
		available_cameras=[
			"Camera-A",
			"Camera-B",
		],
		target_date=target_date,
		requested_cameras=None,
		framerate=MANUAL_FRAMERATE,
	)

	assert processed_cameras == ["Camera-B"]
