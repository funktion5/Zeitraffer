import subprocess
from datetime import date, datetime
from pathlib import Path

import src.jobs.weekly as weekly_module

TEST_CONFIG = {
    "location": {
        "latitude": 52.0,
        "longitude": 9.0,
        "timezone": "Europe/Berlin",
    }
}


# Return exactly seven expected Daily paths for the rolling window.
def test_get_expected_weekly_video_paths(
    tmp_path: Path,
    monkeypatch,
):
    video_root = tmp_path / "videos"

    monkeypatch.setattr(
        weekly_module,
        "VIDEO_ROOT",
        video_root,
    )

    result = (
        weekly_module.get_expected_weekly_video_paths(
            camera="Scheunenviertel",
            end_date=date(
                2026,
                9,
                16,
            ),
        )
    )

    assert result == [
        (
            video_root
            / "Scheunenviertel"
            / "daily"
            / "Scheunenviertel_2026-09-10.mp4"
        ),
        (
            video_root
            / "Scheunenviertel"
            / "daily"
            / "Scheunenviertel_2026-09-11.mp4"
        ),
        (
            video_root
            / "Scheunenviertel"
            / "daily"
            / "Scheunenviertel_2026-09-12.mp4"
        ),
        (
            video_root
            / "Scheunenviertel"
            / "daily"
            / "Scheunenviertel_2026-09-13.mp4"
        ),
        (
            video_root
            / "Scheunenviertel"
            / "daily"
            / "Scheunenviertel_2026-09-14.mp4"
        ),
        (
            video_root
            / "Scheunenviertel"
            / "daily"
            / "Scheunenviertel_2026-09-15.mp4"
        ),
        (
            video_root
            / "Scheunenviertel"
            / "daily"
            / "Scheunenviertel_2026-09-16.mp4"
        ),
    ]


# Return all seven videos when the complete rolling window exists.
def test_get_weekly_daily_videos_returns_complete_window(
    tmp_path: Path,
    monkeypatch,
):
    video_root = tmp_path / "videos"

    monkeypatch.setattr(
        weekly_module,
        "VIDEO_ROOT",
        video_root,
    )

    daily_directory = (
        video_root
        / "Scheunenviertel"
        / "daily"
    )

    daily_directory.mkdir(
        parents=True
    )

    expected_videos = []

    for day in range(
        10,
        17,
    ):
        video = (
            daily_directory
            / f"Scheunenviertel_2026-09-{day:02d}.mp4"
        )

        video.touch()
        expected_videos.append(
            video
        )

    result = (
        weekly_module.get_weekly_daily_videos(
            camera="Scheunenviertel",
            end_date=date(
                2026,
                9,
                16,
            ),
        )
    )

    assert result == expected_videos


# Missing days must remain missing and must not be filled by older videos.
def test_get_weekly_daily_videos_keeps_gap(
    tmp_path: Path,
    monkeypatch,
):
    video_root = tmp_path / "videos"

    monkeypatch.setattr(
        weekly_module,
        "VIDEO_ROOT",
        video_root,
    )

    daily_directory = (
        video_root
        / "Scheunenviertel"
        / "daily"
    )

    daily_directory.mkdir(
        parents=True
    )

    for day in [
        10,
        11,
        12,
        13,
        15,
        16,
    ]:
        (
            daily_directory
            / f"Scheunenviertel_2026-09-{day:02d}.mp4"
        ).touch()

    older_video = (
        daily_directory
        / "Scheunenviertel_2026-09-09.mp4"
    )

    older_video.touch()

    result = (
        weekly_module.get_weekly_daily_videos(
            camera="Scheunenviertel",
            end_date=date(
                2026,
                9,
                16,
            ),
        )
    )

    assert len(result) == 6

    assert older_video not in result

    assert (
        daily_directory
        / "Scheunenviertel_2026-09-14.mp4"
    ) not in result


# Ignore Daily videos older than the rolling seven-day window.
def test_get_weekly_daily_videos_ignores_older_videos(
    tmp_path: Path,
    monkeypatch,
):
    video_root = tmp_path / "videos"

    monkeypatch.setattr(
        weekly_module,
        "VIDEO_ROOT",
        video_root,
    )

    daily_directory = (
        video_root
        / "Scheunenviertel"
        / "daily"
    )

    daily_directory.mkdir(
        parents=True
    )

    older_video = (
        daily_directory
        / "Scheunenviertel_2026-09-09.mp4"
    )

    current_video = (
        daily_directory
        / "Scheunenviertel_2026-09-16.mp4"
    )

    older_video.touch()
    current_video.touch()

    result = (
        weekly_module.get_weekly_daily_videos(
            camera="Scheunenviertel",
            end_date=date(
                2026,
                9,
                16,
            ),
        )
    )

    assert result == [
        current_video
    ]


# Return available Daily videos in chronological order.
def test_get_weekly_daily_videos_returns_chronological_order(
    tmp_path: Path,
    monkeypatch,
):
    video_root = tmp_path / "videos"

    monkeypatch.setattr(
        weekly_module,
        "VIDEO_ROOT",
        video_root,
    )

    daily_directory = (
        video_root
        / "Scheunenviertel"
        / "daily"
    )

    daily_directory.mkdir(
        parents=True
    )

    video_16 = (
        daily_directory
        / "Scheunenviertel_2026-09-16.mp4"
    )

    video_10 = (
        daily_directory
        / "Scheunenviertel_2026-09-10.mp4"
    )

    video_13 = (
        daily_directory
        / "Scheunenviertel_2026-09-13.mp4"
    )

    video_16.touch()
    video_10.touch()
    video_13.touch()

    result = (
        weekly_module.get_weekly_daily_videos(
            camera="Scheunenviertel",
            end_date=date(
                2026,
                9,
                16,
            ),
        )
    )

    assert result == [
        video_10,
        video_13,
        video_16,
    ]


# Ignore unrelated files inside the Daily directory.
def test_get_weekly_daily_videos_ignores_unrelated_files(
    tmp_path: Path,
    monkeypatch,
):
    video_root = tmp_path / "videos"

    monkeypatch.setattr(
        weekly_module,
        "VIDEO_ROOT",
        video_root,
    )

    daily_directory = (
        video_root
        / "Scheunenviertel"
        / "daily"
    )

    daily_directory.mkdir(
        parents=True
    )

    valid_video = (
        daily_directory
        / "Scheunenviertel_2026-09-16.mp4"
    )

    valid_video.touch()

    (
        daily_directory
        / "random.mp4"
    ).touch()

    (
        daily_directory
        / "notes.txt"
    ).touch()

    result = (
        weekly_module.get_weekly_daily_videos(
            camera="Scheunenviertel",
            end_date=date(
                2026,
                9,
                16,
            ),
        )
    )

    assert result == [
        valid_video
    ]


# Return missing Daily paths inside the rolling seven-day window.
def test_get_missing_weekly_video_paths(
    tmp_path: Path,
    monkeypatch,
):
    video_root = tmp_path / "videos"

    monkeypatch.setattr(
        weekly_module,
        "VIDEO_ROOT",
        video_root,
    )

    daily_directory = (
        video_root
        / "Scheunenviertel"
        / "daily"
    )

    daily_directory.mkdir(
        parents=True
    )

    for day in [
        10,
        11,
        12,
        13,
        15,
        16,
    ]:
        (
            daily_directory
            / f"Scheunenviertel_2026-09-{day:02d}.mp4"
        ).touch()

    result = (
        weekly_module.get_missing_weekly_video_paths(
            camera="Scheunenviertel",
            end_date=date(
                2026,
                9,
                16,
            ),
        )
    )

    assert result == [
        (
            daily_directory
            / "Scheunenviertel_2026-09-14.mp4"
        )
    ]


# Create a Weekly from the available Daily videos even when days are missing.
def test_create_weekly_video_uses_available_dailies(
    tmp_path: Path,
    monkeypatch,
    caplog,
):
    video_root = tmp_path / "videos"
    temp_root = tmp_path / "temp"

    monkeypatch.setattr(
        weekly_module,
        "VIDEO_ROOT",
        video_root,
    )

    monkeypatch.setattr(
        weekly_module,
        "TEMP_ROOT",
        temp_root,
    )

    daily_directory = (
        video_root
        / "Scheunenviertel"
        / "daily"
    )

    daily_directory.mkdir(
        parents=True
    )

    available_video = (
        daily_directory
        / "Scheunenviertel_2026-09-16.mp4"
    )

    available_video.touch()

    concat_calls = []

    def fake_create_concat_file(
        videos,
        temp_directory,
    ):
        concat_calls.append(
            {
                "videos": videos,
                "temp_directory": temp_directory,
            }
        )

        return (
            temp_directory
            / "concat.txt"
        )

    monkeypatch.setattr(
        weekly_module,
        "create_concat_file",
        fake_create_concat_file,
    )

    output_path = (
        video_root
        / "Scheunenviertel"
        / "weekly"
        / "Scheunenviertel_weekly.mp4"
    )

    concat_video_calls = []

    def fake_create_concat_video(
        concat_path,
        output_path,
    ):
        concat_video_calls.append(
            {
                "concat_path": concat_path,
                "output_path": output_path,
            }
        )

        return output_path

    monkeypatch.setattr(
        weekly_module,
        "create_concat_video",
        fake_create_concat_video,
    )

    cleanup_calls = []

    monkeypatch.setattr(
        weekly_module,
        "cleanup_temp_directory",
        lambda temp_directory: cleanup_calls.append(
            temp_directory
        ),
    )

    result = (
        weekly_module.create_weekly_video(
            camera="Scheunenviertel",
            end_date=date(
                2026,
                9,
                16,
            ),
        )
    )

    expected_temp_directory = (
        temp_root
        / "Scheunenviertel"
        / "weekly"
        / "2026-09-16"
    )

    assert result == output_path

    assert concat_calls == [
        {
            "videos": [
                available_video
            ],
            "temp_directory": (
                expected_temp_directory
            ),
        }
    ]

    assert concat_video_calls == [
        {
            "concat_path": (
                expected_temp_directory
                / "concat.txt"
            ),
            "output_path": output_path,
        }
    ]

    assert cleanup_calls == [
        expected_temp_directory
    ]

    assert (
        "Weekly will be created with "
        "1 of 7 Daily videos."
        in caplog.text
    )


# Skip Weekly creation when no Daily videos are available.
def test_create_weekly_video_skips_when_no_dailies_exist(
    tmp_path: Path,
    monkeypatch,
):
    video_root = tmp_path / "videos"
    temp_root = tmp_path / "temp"

    monkeypatch.setattr(
        weekly_module,
        "VIDEO_ROOT",
        video_root,
    )

    monkeypatch.setattr(
        weekly_module,
        "TEMP_ROOT",
        temp_root,
    )

    concat_file_called = False
    concat_video_called = False

    def fake_create_concat_file(
        videos,
        temp_directory,
    ):
        nonlocal concat_file_called
        concat_file_called = True

    def fake_create_concat_video(
        concat_path,
        output_path,
    ):
        nonlocal concat_video_called
        concat_video_called = True

    monkeypatch.setattr(
        weekly_module,
        "create_concat_file",
        fake_create_concat_file,
    )

    monkeypatch.setattr(
        weekly_module,
        "create_concat_video",
        fake_create_concat_video,
    )

    result = (
        weekly_module.create_weekly_video(
            camera="Scheunenviertel",
            end_date=date(
                2026,
                9,
                16,
            ),
        )
    )

    assert result is None
    assert concat_file_called is False
    assert concat_video_called is False


# Keep Weekly temporary files when video creation fails.
def test_create_weekly_video_keeps_temp_on_error(
    tmp_path: Path,
    monkeypatch,
):
    video_root = tmp_path / "videos"
    temp_root = tmp_path / "temp"

    monkeypatch.setattr(
        weekly_module,
        "VIDEO_ROOT",
        video_root,
    )

    monkeypatch.setattr(
        weekly_module,
        "TEMP_ROOT",
        temp_root,
    )

    daily_directory = (
        video_root
        / "Scheunenviertel"
        / "daily"
    )

    daily_directory.mkdir(
        parents=True
    )

    (
        daily_directory
        / "Scheunenviertel_2026-09-16.mp4"
    ).touch()

    monkeypatch.setattr(
        weekly_module,
        "create_concat_file",
        lambda videos, temp_directory: (
            temp_directory
            / "concat.txt"
        ),
    )

    def fake_create_concat_video(
        concat_path,
        output_path,
    ):
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=["ffmpeg"],
        )

    monkeypatch.setattr(
        weekly_module,
        "create_concat_video",
        fake_create_concat_video,
    )

    cleanup_called = False

    def fake_cleanup_temp_directory(
        temp_directory,
    ):
        nonlocal cleanup_called
        cleanup_called = True

    monkeypatch.setattr(
        weekly_module,
        "cleanup_temp_directory",
        fake_cleanup_temp_directory,
    )

    try:
        weekly_module.create_weekly_video(
            camera="Scheunenviertel",
            end_date=date(
                2026,
                9,
                16,
            ),
        )

    except subprocess.CalledProcessError:
        pass

    assert cleanup_called is False


# Weekly jobs must process yesterday as the end of the rolling window.
def test_run_weekly_job_uses_yesterday(
    monkeypatch,
):
    class FakeDateTime:
        @classmethod
        def now(cls, tz=None):
            return datetime(
                2026,
                9,
                17,
                2,
                0,
                tzinfo=tz,
            )

    monkeypatch.setattr(
        weekly_module,
        "datetime",
        FakeDateTime,
    )

    weekly_calls = []

    def fake_create_weekly_video(
        camera,
        end_date,
    ):
        weekly_calls.append(
            {
                "camera": camera,
                "end_date": end_date,
            }
        )

        return Path(
            f"videos/{camera}/weekly/"
            f"{camera}_weekly.mp4"
        )

    monkeypatch.setattr(
        weekly_module,
        "create_weekly_video",
        fake_create_weekly_video,
    )

    weekly_module.run_weekly_job(
        config=TEST_CONFIG,
        cameras=[
            "Camera-A",
            "Camera-B",
        ],
    )

    assert weekly_calls == [
        {
            "camera": "Camera-A",
            "end_date": date(
                2026,
                9,
                16,
            ),
        },
        {
            "camera": "Camera-B",
            "end_date": date(
                2026,
                9,
                16,
            ),
        },
    ]