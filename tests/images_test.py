import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import src.images as images_module
from src.images import (
    extract_date,
    extract_time,
    find_images,
    find_images_for_date,
    find_interval_images,
    find_interval_images_isolated,
    get_cameras,
    get_image_range,
)
from src.solar import get_sun_times


def test_cameras_with_known_dates():
    # Use known dates with existing images to verify that the date-based
    # image search works across different cameras and filename formats.
    cameras = {
        "BSV-Steinhude": date(2025, 10, 9),
        "Nordufer_tele": date(2025, 4, 19),
        "Nordufer_wide": date(2025, 4, 19),
        "Reolink": date(2025, 10, 24),
        "Wunstorf-Marktplatz": date(2024, 10, 30),
    }

    for camera, target_date in cameras.items():
        images = find_images_for_date(camera, target_date)

        # Verify that the search finds at least one image for every
        # camera on its known test date.
        assert len(images) > 0, (
            f"No images found for camera '{camera}' "
            f"on {target_date}."
        )


def test_extract_time_from_camera_filenames():
    # Real filename examples from the different camera systems.
    # Each filename is mapped to the time expected from extract_time().
    test_cases = {
        "20260915T145103.jpg": (14, 51, 3),
        "scheunenviertel-26-09-15_14-29-56-39.jpg": (14, 29, 56),
        "aw10_26-08-27_15-52-07-75.jpg": (15, 52, 7),
        "see-26-09-15_14-44-58-48.jpg": (14, 44, 58),
        "bsv_steinhude_2510091630.jpg": (16, 30, 0),
        "image_241030_010043.jpg": (1, 0, 43),
        "P23091411034310.jpg": (11, 3, 43),
        "T23091315270800.jpg": (15, 27, 8),
        "Nordufer_tele_20250419T094017.jpg": (9, 40, 17),
        "Nordufer_wide_20250419T100009.jpg": (10, 0, 9),
        "sam-Reolink_00_20251024145546.jpg": (14, 55, 46),
    }

    for filename, expected_time in test_cases.items():
        result = extract_time(filename)

        # Verify that every supported filename format returns
        # the correct hour, minute and second.
        assert result == expected_time, (
            f"Wrong time extracted from '{filename}': "
            f"expected {expected_time}, got {result}"
        )


def test_extract_date_from_camera_filenames():
	# Real filename examples from the different camera systems.
	test_cases = {
		"20260915T145103.jpg": date(2026, 9, 15),
		"scheunenviertel-26-09-15_14-29-56-39.jpg": date(2026, 9, 15),
		"aw10_26-08-27_15-52-07-75.jpg": date(2026, 8, 27),
		"see-26-09-15_14-44-58-48.jpg": date(2026, 9, 15),
		"bsv_steinhude_2510091630.jpg": date(2025, 10, 9),
        "bsv_steinhude_202410020900.jpg": date(2024, 10, 2),
        "bsv_steinhude_202312181415.jpg": date(2023, 12, 18),
		"image_241030_010043.jpg": date(2024, 10, 30),
		"P23091411034310.jpg": date(2023, 9, 14),
		"T23091315270800.jpg": date(2023, 9, 13),
		"Nordufer_tele_20250419T094017.jpg": date(2025, 4, 19),
		"Nordufer_wide_20250419T100009.jpg": date(2025, 4, 19),
		"sam-Reolink_00_20251024145546.jpg": date(2025, 10, 24),
	}

	for filename, expected_date in test_cases.items():
		result = extract_date(filename)

		assert result == expected_date, (
			f"Wrong date extracted from '{filename}': "
			f"expected {expected_date}, got {result}"
		)


def test_extract_date_rejects_invalid_filenames():
	# Filenames without a supported or valid camera date must be rejected.
	invalid_filenames = [
		"random_image.jpg",
		"image_without_date.jpg",
		"20261340T145103.jpg",
		"scheunenviertel-26-99-99_14-29-56-39.jpg",
		"bsv_steinhude_9999991630.jpg",
		"image_999999_010043.jpg",
	]

	for filename in invalid_filenames:
		assert extract_date(filename) is None     

def test_complete_image_selection():
    # Use known camera/date combinations to test the complete selection
    # workflow: find images, extract timestamps and apply the daylight window.
    cameras = {
        "BSV-Steinhude": date(2025, 10, 9),
        "Nordufer_tele": date(2025, 4, 19),
        "Nordufer_wide": date(2025, 4, 19),
        "Reolink": date(2025, 10, 24),
        "Scheunenviertel": date(2026, 9, 14),
        "Wunstorf-Marktplatz": date(2023, 1, 31),
    }

    for camera, target_date in cameras.items():
        # Calculate the daylight window for the selected date.
        sunrise, sunset = get_sun_times(
            target_date=target_date,
            latitude=52.45,
            longitude=9.38,
            timezone="Europe/Berlin",
        )

        # Run the same image-selection logic used by the application.
        images = find_images(
            camera=camera,
            target_date=target_date,
            sunrise=sunrise,
            sunset=sunset,
            daylight_buffer_minutes=90,
        )

        # Verify that at least one image remains after daylight filtering.
        assert len(images) > 0, (
            f"No daylight images found for camera '{camera}' "
            f"on {target_date}."
        )


def test_get_cameras():
    # Read the available cameras dynamically from the mounted camera storage.
    cameras = get_cameras()

    # Verify that camera discovery returns at least one directory.
    assert len(cameras) > 0

    # Verify that camera names are returned in a predictable sorted order.
    assert cameras == sorted(cameras)

    # Verify that hidden system directories such as .ssh are ignored.
    assert all(not camera.startswith(".") for camera in cameras)
    

def test_get_image_range(tmp_path, monkeypatch):
	camera_root = tmp_path / "cameras"
	camera_directory = camera_root / "Test-Camera"
	camera_directory.mkdir(parents=True)

	# Create supported filenames across different dates.
	(camera_directory / "20260915T145103.jpg").touch()
	(camera_directory / "20260910T120000.jpg").touch()
	(camera_directory / "20260920T180000.jpg").touch()

	# Simulate a new or unsupported camera filename format.
	(camera_directory / "unknown-camera-format.jpg").touch()

	monkeypatch.setattr("src.images.CAMERA_ROOT", camera_root)

	result = get_image_range("Test-Camera")

	assert result.earliest_date == date(2026, 9, 10)
	assert result.latest_date == date(2026, 9, 20)

	assert result.total_files == 4
	assert result.recognized_files == 3
	assert result.unrecognized_files == 1    


def test_get_image_range_with_unknown_format(tmp_path, monkeypatch):
	# Simulate a new camera whose filename format is completely unknown.
	camera_root = tmp_path / "cameras"
	camera_directory = camera_root / "New-Camera"
	camera_directory.mkdir(parents=True)

	(camera_directory / "capture-alpha.jpg").touch()
	(camera_directory / "photo-something.jpg").touch()
	(camera_directory / "new-system-file.jpg").touch()

	monkeypatch.setattr("src.images.CAMERA_ROOT", camera_root)

	result = get_image_range("New-Camera")

	# Files exist, but none of their dates can be safely determined.
	assert result.total_files == 3
	assert result.recognized_files == 0
	assert result.unrecognized_files == 3

	# Never guess a date when the filename format is unsupported.
	assert result.earliest_date is None
	assert result.latest_date is None

def test_find_images_uses_daylight_buffer(monkeypatch):
    target_date = date(2026, 9, 16)
    timezone = ZoneInfo("Europe/Berlin")

    sunrise = datetime(
        2026,
        9,
        16,
        7,
        0,
        tzinfo=timezone,
    )
    sunset = datetime(
        2026,
        9,
        16,
        19,
        0,
        tzinfo=timezone,
    )

    test_images = [
        Path("camera_26-09-16_06-29-00-00.jpg"),
        Path("camera_26-09-16_06-31-00-00.jpg"),
        Path("camera_26-09-16_19-29-00-00.jpg"),
        Path("camera_26-09-16_19-31-00-00.jpg"),
    ]

    def fake_find_images_for_date(
        camera,
        target_date,
        progress_callback=None,
    ):
        return test_images

    monkeypatch.setattr(
        images_module,
        "find_images_for_date",
        fake_find_images_for_date,
    )

    result = images_module.find_images(
        camera="Test-Camera",
        target_date=target_date,
        sunrise=sunrise,
        sunset=sunset,
        daylight_buffer_minutes=30,
    )

    assert result == [
        Path("camera_26-09-16_06-31-00-00.jpg"),
        Path("camera_26-09-16_19-29-00-00.jpg"),
    ]

def test_find_images_for_date_scans_directory_once(
    tmp_path,
    monkeypatch,
):
    camera_root = tmp_path / "cameras"
    camera_directory = (
        camera_root
        / "Test-Camera"
    )

    camera_directory.mkdir(
        parents=True
    )

    expected_images = [
        camera_directory
        / "camera_26-09-16_10-00-00-00.jpg",
        camera_directory
        / "camera_20260916T120000.jpg",
    ]

    for image in expected_images:
        image.touch()

    (
        camera_directory
        / "camera_26-09-15_10-00-00-00.jpg"
    ).touch()

    monkeypatch.setattr(
        images_module,
        "CAMERA_ROOT",
        camera_root,
    )

    original_scandir = images_module.os.scandir
    scandir_calls = []

    def fake_scandir(path):
        scandir_calls.append(
            path
        )

        return original_scandir(
            path
        )

    monkeypatch.setattr(
        images_module.os,
        "scandir",
        fake_scandir,
    )

    result = (
        images_module.find_images_for_date(
            camera="Test-Camera",
            target_date=date(
                2026,
                9,
                16,
            ),
        )
    )

    assert result == sorted(
        expected_images
    )

    assert scandir_calls == [
        camera_directory
    ]


def test_get_image_range_uses_filename_scan_only(
    tmp_path,
    monkeypatch,
):
    camera_root = tmp_path / "cameras"
    camera_directory = (
        camera_root
        / "Test-Camera"
    )

    camera_directory.mkdir(
        parents=True
    )

    (
        camera_directory
        / "20260910T120000.jpg"
    ).touch()

    (
        camera_directory
        / "20260920T180000.jpg"
    ).touch()

    (
        camera_directory
        / "unknown-format.jpg"
    ).touch()

    (
        camera_directory
        / "notes.txt"
    ).touch()

    (
        camera_directory
        / "directory.jpg"
    ).mkdir()

    monkeypatch.setattr(
        images_module,
        "CAMERA_ROOT",
        camera_root,
    )

    result = (
        images_module.get_image_range(
            "Test-Camera"
        )
    )

    assert result.earliest_date == date(
        2026,
        9,
        10,
    )

    assert result.latest_date == date(
        2026,
        9,
        20,
    )

    assert result.total_files == 4
    assert result.recognized_files == 2
    assert result.unrecognized_files == 2


# A scan that stops reporting progress must be terminated after the stall timeout.
def test_find_images_isolated_stops_stalled_scan(
    monkeypatch,
):
    created_processes = []
    created_queues = []

    timezone = ZoneInfo(
    "Europe/Berlin")

    # Simulate a worker that never sends progress or a result.
    class FakeQueue:
        def __init__(self):
            self.closed = False
            self.get_timeouts = []

            created_queues.append(
                self
            )

        def get(
            self,
            timeout,
        ):
            self.get_timeouts.append(
                timeout
            )

            raise images_module.Empty

        def close(self):
            self.closed = True

    class FakeProcess:
        def __init__(
            self,
            target,
            args,
            daemon,
        ):
            self.target = target
            self.args = args
            self.daemon = daemon

            self.started = False
            self.alive = True
            self.terminated = False
            self.join_calls = []

            created_processes.append(
                self
            )

        def start(self):
            self.started = True

        def is_alive(self):
            return self.alive

        def terminate(self):
            self.terminated = True
            self.alive = False

        def join(
            self,
            timeout=None,
        ):
            self.join_calls.append(
                timeout
            )

    # Simulate two five-second polling intervals without any progress.
    monotonic_values = iter(
        [
            0,
            0,
            5,
            10,
        ]
    )

    monkeypatch.setattr(
        images_module,
        "Queue",
        FakeQueue,
    )

    monkeypatch.setattr(
        images_module,
        "Process",
        FakeProcess,
    )

    monkeypatch.setattr(
        images_module.time,
        "monotonic",
        lambda: next(
            monotonic_values
        ),
    )

    with pytest.raises(
        TimeoutError,
        match="Image scan stalled for camera: Test-Camera",
    ):
        images_module.find_images_isolated(
            camera="Test-Camera",
            target_date=date(
                2026,
                9,
                16,
            ),
            sunrise=datetime(
                2026,
                9,
                16,
                7,
                0,
                tzinfo=timezone,
            ),
            sunset=datetime(
                2026,
                9,
                16,
                19,
                0,
                tzinfo=timezone,
            ),
            daylight_buffer_minutes=90,
            stall_timeout_seconds=10,
        )

    process = created_processes[0]
    result_queue = created_queues[0]

    assert process.started is True
    assert process.terminated is True
    assert process.alive is False

    assert result_queue.get_timeouts == [
        5,
        5,
    ]

    assert result_queue.closed is True

# Progress must reset the stall timeout so long-running scans can continue.
def test_find_images_isolated_resets_stall_timeout_on_progress(
	monkeypatch,
):
	created_processes = []
	created_queues = []

	timezone = ZoneInfo(
		"Europe/Berlin"
	)

	class FakeQueue:
		def __init__(self):
			self.closed = False
			self.responses = iter(
				[
					(
						"progress",
						None,
					),
					(
						"success",
						[
							Path(
								"image.jpg"
							)
						],
					),
				]
			)

			created_queues.append(
				self
			)

		def get(
			self,
			timeout,
		):
			return next(
				self.responses
			)

		def close(self):
			self.closed = True

	class FakeProcess:
		def __init__(
			self,
			target,
			args,
			daemon,
		):
			self.target = target
			self.args = args
			self.daemon = daemon

			self.started = False
			self.alive = True
			self.join_calls = []

			created_processes.append(
				self
			)

		def start(self):
			self.started = True

		def is_alive(self):
			return self.alive

		def join(
			self,
			timeout=None,
		):
			self.join_calls.append(
				timeout
			)

			self.alive = False

    # Total runtime exceeds the timeout, but progress at second 9 resets inactivity.
	monotonic_values = iter(
		[
			0,
			9,
			9,
            15,
		]
	)

	monkeypatch.setattr(
		images_module,
		"Queue",
		FakeQueue,
	)

	monkeypatch.setattr(
		images_module,
		"Process",
		FakeProcess,
	)

	monkeypatch.setattr(
		images_module.time,
		"monotonic",
		lambda: next(
			monotonic_values
		),
	)

	result = images_module.find_images_isolated(
		camera="Test-Camera",
		target_date=date(
			2026,
			9,
			16,
		),
		sunrise=datetime(
			2026,
			9,
			16,
			7,
			0,
			tzinfo=timezone,
		),
		sunset=datetime(
			2026,
			9,
			16,
			19,
			0,
			tzinfo=timezone,
		),
		daylight_buffer_minutes=90,
		stall_timeout_seconds=10,
	)

	assert result == [
		Path(
			"image.jpg"
		)
	]

	assert created_processes[0].started is True
	assert created_queues[0].closed is True

# Empty image files must be removed and reported before video processing.
def test_validate_images_removes_empty_files(
	tmp_path,
	monkeypatch,
):
	first_image = (
		tmp_path
		/ "first.jpg"
	)

	empty_image = (
		tmp_path
		/ "empty.jpg"
	)

	second_image = (
		tmp_path
		/ "second.jpg"
	)

	first_image.write_bytes(
		b"image data"
	)

	empty_image.touch()

	second_image.write_bytes(
		b"more image data"
	)

	warnings = []

	monkeypatch.setattr(
		images_module.logger,
		"warning",
		lambda message: warnings.append(
			message
		),
	)

	result = images_module.validate_images(
		camera="Test-Camera",
		images=[
			first_image,
			empty_image,
			second_image,
		],
	)

	assert result == [
		first_image,
		second_image,
	]

	assert warnings == [
		"Camera Test-Camera: removed 1 empty image files"
	]
# Identical image data must be detected without removing valid files.
def test_validate_images_logs_duplicate_source_data(
	tmp_path,
	monkeypatch,
):
	first_image = (
		tmp_path
		/ "first.jpg"
	)

	duplicate_image = (
		tmp_path
		/ "duplicate.jpg"
	)

	different_image = (
		tmp_path
		/ "different.jpg"
	)

	first_image.write_bytes(
		b"same image data"
	)

	duplicate_image.write_bytes(
		b"same image data"
	)

	different_image.write_bytes(
		b"different image"
	)

	warnings = []

	monkeypatch.setattr(
		images_module.logger,
		"warning",
		lambda message: warnings.append(
			message
		),
	)

	result = images_module.validate_images(
		camera="Test-Camera",
		images=[
			first_image,
			duplicate_image,
			different_image,
		],
	)

	assert result == [
		first_image,
		duplicate_image,
		different_image,
	]

	assert warnings == [
        (
	    	"Camera Test-Camera: detected "
		    "2 images with duplicate source data "
		    "in 1 duplicate groups"
        )
	]

# Hash progress must be rate-limited while large files are processed.
def test_get_image_hash_limits_progress_reports(
	tmp_path,
	monkeypatch,
):
	image_path = (
		tmp_path
		/ "large.jpg"
	)

	image_path.write_bytes(
		b"a" * (3 * 1024 * 1024)
	)

	monotonic_values = iter(
		[
			0,
			0.2,
			1.1,
			1.2,
		]
	)

	monkeypatch.setattr(
		images_module.time,
		"monotonic",
		lambda: next(
			monotonic_values
		),
	)

	progress_calls = []

	images_module._get_image_hash(
		image_path=image_path,
		progress_callback=lambda: progress_calls.append(
			True
		),
	)

	assert len(progress_calls) == 1

def test_find_interval_images_returns_all_images_inside_daily_window(
	tmp_path,
	monkeypatch,
):
	camera_root = (
		tmp_path
		/ "cameras"
	)

	camera_directory = (
		camera_root
		/ "Test-Camera"
	)

	camera_directory.mkdir(
		parents=True
	)

	filenames = [
		"camera_26-09-15_10-20-00-00.jpg",
		"camera_26-09-15_10-30-00-00.jpg",
		"camera_26-09-15_11-15-00-00.jpg",
		"camera_26-09-15_12-02-00-00.jpg",
		"camera_26-09-15_13-30-00-00.jpg",
		"camera_26-09-15_13-31-00-00.jpg",
	]

	for filename in filenames:
		(
			camera_directory
			/ filename
		).touch()

	monkeypatch.setattr(
		images_module,
		"CAMERA_ROOT",
		camera_root,
	)

	result = find_interval_images(
		camera="Test-Camera",
		start_date=date(
			2026,
			9,
			15,
		),
		end_date=date(
			2026,
			9,
			15,
		),
	)

	assert result == [
		camera_directory
		/ "camera_26-09-15_10-30-00-00.jpg",
		camera_directory
		/ "camera_26-09-15_11-15-00-00.jpg",
		camera_directory
		/ "camera_26-09-15_12-02-00-00.jpg",
		camera_directory
		/ "camera_26-09-15_13-30-00-00.jpg",
	]


def test_find_interval_images_respects_target_tolerance(
	tmp_path,
	monkeypatch,
):
	camera_root = (
		tmp_path
		/ "cameras"
	)

	camera_directory = (
		camera_root
		/ "Test-Camera"
	)

	camera_directory.mkdir(
		parents=True
	)

	inside_tolerance = (
		camera_directory
		/ "camera_26-09-15_10-30-00-00.jpg"
	)

	outside_tolerance = (
		camera_directory
		/ "camera_26-09-16_10-29-59-00.jpg"
	)

	inside_tolerance.touch()
	outside_tolerance.touch()

	monkeypatch.setattr(
		images_module,
		"CAMERA_ROOT",
		camera_root,
	)

	result = find_interval_images(
		camera="Test-Camera",
		start_date=date(
			2026,
			9,
			15,
		),
		end_date=date(
			2026,
			9,
			16,
		),
		tolerance_minutes=90,
	)

	assert result == [
		inside_tolerance
	]


def test_find_interval_images_scans_directory_once(
	tmp_path,
	monkeypatch,
):
	camera_root = (
		tmp_path
		/ "cameras"
	)

	camera_directory = (
		camera_root
		/ "Test-Camera"
	)

	camera_directory.mkdir(
		parents=True
	)

	(
		camera_directory
		/ "camera_26-09-15_12-00-00-00.jpg"
	).touch()

	(
		camera_directory
		/ "camera_26-09-16_12-00-00-00.jpg"
	).touch()

	monkeypatch.setattr(
		images_module,
		"CAMERA_ROOT",
		camera_root,
	)

	original_scandir = (
		images_module.os.scandir
	)

	scandir_calls = []

	def fake_scandir(path):
		scandir_calls.append(
			path
		)

		return original_scandir(
			path
		)

	monkeypatch.setattr(
		images_module.os,
		"scandir",
		fake_scandir,
	)

	result = find_interval_images(
		camera="Test-Camera",
		start_date=date(
			2026,
			9,
			15,
		),
		end_date=date(
			2026,
			9,
			16,
		),
	)

	assert len(result) == 2

	assert scandir_calls == [
		camera_directory
	]

def test_find_interval_images_returns_images_in_chronological_order(
	tmp_path,
	monkeypatch,
):
	camera_root = (
		tmp_path
		/ "cameras"
	)

	camera_directory = (
		camera_root
		/ "Test-Camera"
	)

	camera_directory.mkdir(
		parents=True
	)

	filenames = [
		"camera_26-09-16_12-30-00-00.jpg",
		"camera_26-09-15_13-00-00-00.jpg",
		"camera_26-09-16_10-45-00-00.jpg",
		"camera_26-09-15_11-00-00-00.jpg",
	]

	for filename in filenames:
		(
			camera_directory
			/ filename
		).touch()

	monkeypatch.setattr(
		images_module,
		"CAMERA_ROOT",
		camera_root,
	)

	result = find_interval_images(
		camera="Test-Camera",
		start_date=date(
			2026,
			9,
			15,
		),
		end_date=date(
			2026,
			9,
			16,
		),
	)

	assert result == [
		camera_directory
		/ "camera_26-09-15_11-00-00-00.jpg",
		camera_directory
		/ "camera_26-09-15_13-00-00-00.jpg",
		camera_directory
		/ "camera_26-09-16_10-45-00-00.jpg",
		camera_directory
		/ "camera_26-09-16_12-30-00-00.jpg",
	]

def test_find_interval_images_isolated_returns_validated_images(
	tmp_path,
	monkeypatch,
):
	camera_root = (
		tmp_path
		/ "cameras"
	)

	camera_directory = (
		camera_root
		/ "Test-Camera"
	)

	camera_directory.mkdir(
		parents=True
	)

	valid_image = (
		camera_directory
		/ "camera_26-09-15_12-00-00-00.jpg"
	)

	empty_image = (
		camera_directory
		/ "camera_26-09-15_12-10-00-00.jpg"
	)

	valid_image.write_bytes(
		b"valid image"
	)

	empty_image.touch()

	monkeypatch.setattr(
		images_module,
		"CAMERA_ROOT",
		camera_root,
	)

	result = find_interval_images_isolated(
		camera="Test-Camera",
		start_date=date(
			2026,
			9,
			15,
		),
		end_date=date(
			2026,
			9,
			15,
		),
		stall_timeout_seconds=2,
	)

	# The isolated pipeline must return only validated interval images.
	assert result == [
		valid_image
	]

def test_find_interval_images_isolated_stops_stalled_scan(
	monkeypatch,
):
	def stalled_worker(
		camera,
		start_date,
		end_date,
		target_hour,
		target_minute,
		tolerance_minutes,
		result_queue,
	):
		while True:
			time.sleep(
				1
			)

	monkeypatch.setattr(
		images_module,
		"_find_interval_images_worker",
		stalled_worker,
	)

	start_time = time.monotonic()

	try:
		find_interval_images_isolated(
			camera="Test-Camera",
			start_date=date(
				2026,
				9,
				15,
			),
			end_date=date(
				2026,
				9,
				16,
			),
			stall_timeout_seconds=0.2,
		)

		assert False, (
			"Expected TimeoutError"
		)

	except TimeoutError:
		pass

	elapsed = (
		time.monotonic()
		- start_time
	)

	# A blocked camera must not keep the parent process waiting indefinitely.
	assert elapsed < 2