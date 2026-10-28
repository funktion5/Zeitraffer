import subprocess

# Lines of `ls -l` output, the way the Storage Box prints them.
LS_DIRECTORY = "drwxr-xr-x 2 user group 4096 Oct 28 09:00 {}"
LS_FILE = "-rw-r--r-- 1 user group 1234 Oct 28 09:00 {}"
LS_SYMLINK = "lrwxrwxrwx 1 user group 9 Oct 28 09:00 {} -> elsewhere"


# Stands in for StorageBox: answers every command with a canned `ls -l` listing.
class FakeBox:
	remote = "box"
	base_directory = "cameras"

	def __init__(self, lines=(), returncode=0, stderr="", raises=None):
		self.stdout = "\n".join(["total 8", *lines])
		self.returncode = returncode
		self.stderr = stderr
		self.raises = raises
		self.commands = []

	def camera_directory(self, camera):
		return f"{self.base_directory}/{camera}"

	def run(self, command, timeout_seconds):
		self.commands.append((command, timeout_seconds))

		if self.raises is not None:
			raise self.raises

		return subprocess.CompletedProcess([command], self.returncode, self.stdout, self.stderr)
