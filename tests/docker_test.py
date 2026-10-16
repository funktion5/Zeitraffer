from pathlib import Path

from src.config import PROJECT_ROOT

ENTRYPOINT = (PROJECT_ROOT / "docker" / "entrypoint.sh").read_text()
COMPOSE = (PROJECT_ROOT / "compose.yaml").read_text()
DOCKERIGNORE = (PROJECT_ROOT / ".dockerignore").read_text().split()


# The camera mount is the original images: read-only in the container as on the Pi.
def test_container_mounts_the_camera_images_read_only() -> None:
	assert "-o ro" in ENTRYPOINT
	assert "StrictHostKeyChecking=yes" in ENTRYPOINT


# While the Pi is productive, a second live job would write the same camera folders.
def test_live_job_stays_off_in_the_container() -> None:
	assert "src.privacy.blur_box" in ENTRYPOINT
	assert 'ALLOW_BOX_WRITES: "0"' in COMPOSE
	assert 'restart: "no"' in COMPOSE


def test_program_never_runs_as_root() -> None:
	assert ENTRYPOINT.rstrip().splitlines()[-2].startswith("exec setpriv --reuid=app")


# Runtime data, models and secrets never end up in an image layer.
def test_image_excludes_data_models_and_secrets() -> None:
	for entry in ["videos", "state", "logs", "models", "docker-data", "*.env", "*.key", ".git"]:
		assert entry in DOCKERIGNORE


def test_no_real_storage_box_values_in_the_example() -> None:
	example = Path(PROJECT_ROOT / "docker" / "storage-box.env.example").read_text()

	assert "REMOTE_USER=<user>" in example
	assert "REMOTE_HOST=<host>" in example
