"""Copy the pictures of a 2004-2008 camera zip that has no central directory.

Four zips in webcam-archive (promenade, insektenmuseum, uferstrasse, scheunenviertel) end without
a central directory, so zipfile cannot open them. Their entries carry a data descriptor (sizes
unknown up front). This reads the zip front to back over the read-only mount /mnt/nas: deflated
entries are inflated as a stream (zlib reports where each one ends, so no guessing at "PK"
bytes inside compressed data), tars are read with tarfile in stream mode, inner zips are
spilled to temp/ on disk. Same keep rules as zip_extract.py: only names src.images.extract_date
knows, within the given years, existing files kept; unknown names are counted with samples.

Usage: .venv/bin/python3 seqzip_extract.py <zip name> <camera> <first year> <last year>
"""

import collections
import io
import struct
import sys
import tarfile
import zipfile
import zlib
from pathlib import Path

sys.path.insert(0, "/home/zruser/timelapse")

from src.images import extract_date  # noqa: E402

ARCHIVE = Path("/mnt/nas/storagebox-mirror/webcam-bis-2023/Cafe-am-Meer-Promenade/webcam-archive")
LOCAL = 0x04034B50
DESCRIPTOR = 0x08074B50
CHUNK = 4 << 20

zip_name, camera, first_year, last_year = (
	sys.argv[1],
	sys.argv[2],
	int(sys.argv[3]),
	int(sys.argv[4]),
)
target = Path.home() / "nas-cameras" / camera
target.mkdir(parents=True, exist_ok=True)
unknown_samples: list[str] = []


def store(name: str, read, counts: collections.Counter) -> None:
	base = name.rsplit("/", 1)[-1]
	if base.startswith(".") or not base.lower().endswith(".jpg"):
		counts["other"] += 1
		return
	day = extract_date(base)
	if day is None:
		counts["unknown_format"] += 1
		if len(unknown_samples) < 20:
			unknown_samples.append(name)
		return
	if not first_year <= day.year <= last_year:
		counts["outside_years"] += 1
		return
	path = target / base
	if path.exists():
		counts["existing"] += 1
		return
	part = path.with_suffix(".part")
	part.write_bytes(read())
	part.rename(path)
	counts["kept"] += 1


def salvage_local_entries(path: Path, counts: collections.Counter) -> None:
	"""Read an inner zip without its central directory entry by entry, until the data runs out."""
	with path.open("rb") as f:
		while True:
			head = f.read(30)
			if len(head) < 30 or struct.unpack("<I", head[:4])[0] != LOCAL:
				break
			_, _, flag, method, _, _, _, csize, _, nlen, xlen = struct.unpack("<IHHHHHIIIHH", head)
			name = f.read(nlen).decode("cp437")
			f.read(xlen)
			if flag & 8:
				counts["salvage_stopped_at_descriptor"] += 1
				break
			data = f.read(csize)
			if len(data) < csize:
				counts["salvage_cut_entry"] += 1
				break
			if name.endswith("/"):
				continue
			store(name, lambda d=data, m=method: zlib.decompress(d, -15) if m == 8 else d, counts)
		counts["salvaged_without_directory"] += 1


class EntryStream(io.RawIOBase):
	"""File-like view of one entry's uncompressed data; keeps raw bytes read past its end."""

	def __init__(self, raw, method: int, size: int | None):
		self.raw, self.left = raw, size
		self.inflater = zlib.decompressobj(-15) if method == 8 else None
		self.pending = b""
		self.done = False
		self.leftover = b""
		self.last_chunk = b""
		self.failed = False

	def readable(self) -> bool:
		return True

	def _fill(self) -> None:
		while not self.pending and not self.done:
			if self.inflater is not None:
				chunk = self.raw.read(CHUNK)
				if not chunk:
					raise EOFError("zip ended inside a deflated entry")
				self.last_chunk = chunk  # handed back to resync() if inflating fails
				try:
					self.pending = self.inflater.decompress(chunk)
				except zlib.error:
					self.failed = True
					raise
				if self.inflater.eof:
					self.leftover = self.inflater.unused_data
					self.done = True
			else:
				if self.left is None:
					raise ValueError("stored entry without size cannot be streamed")
				chunk = self.raw.read(min(CHUNK, self.left))
				self.left -= len(chunk)
				self.pending = chunk
				if self.left == 0 or not chunk:
					self.done = True

	def readinto(self, buffer) -> int:
		self._fill()
		n = min(len(buffer), len(self.pending))
		buffer[:n] = self.pending[:n]
		self.pending = self.pending[n:]
		return n

	def drain(self) -> None:
		while not self.done or self.pending:
			self.pending = b""
			self._fill()


class Raw:
	"""Sequential reader over the zip with a push-back buffer."""

	def __init__(self, path: Path):
		self.f = open(path, "rb")  # noqa: SIM115
		self.back = b""

	def read(self, n: int) -> bytes:
		if self.back:
			out, self.back = self.back[:n], self.back[n:]
			if len(out) < n:
				out += self.f.read(n - len(out))
			return out
		return self.f.read(n)

	def unread(self, data: bytes) -> None:
		self.back = data + self.back


def resync(raw: Raw, prefix: bytes) -> bool:
	"""Skip forward to the next local header whose name starts with the zip's top folder."""
	signature = struct.pack("<I", LOCAL)
	buffer = b""
	while chunk := raw.read(CHUNK):
		buffer += chunk
		start = 0
		while (index := buffer.find(signature, start)) != -1:
			if len(buffer) - index < 30 + len(prefix):
				break  # header not complete yet, read more first
			name_length = struct.unpack("<H", buffer[index + 26 : index + 28])[0]
			if (
				name_length >= len(prefix)
				and buffer[index + 30 : index + 30 + len(prefix)] == prefix
			):
				raw.unread(buffer[index:])
				return True
			start = index + 1
		buffer = buffer[index:] if index != -1 else buffer[-(30 + len(prefix)) :]
	return False


raw = Raw(ARCHIVE / zip_name)
totals = collections.Counter()
prefix = None
while True:
	head = raw.read(30)
	if len(head) < 30 or struct.unpack("<I", head[:4])[0] != LOCAL:
		break  # end of the local entries (central directory or truncated end)
	_, _, flag, method, _, _, _, csize, _, nlen, xlen = struct.unpack("<IHHHHHIIIHH", head)
	name = raw.read(nlen).decode("cp437")
	raw.read(xlen)
	if prefix is None:
		prefix = name.split("/", 1)[0].encode("cp437") + b"/"
	sized = not flag & 8
	stream = EntryStream(raw, method, csize if sized else None)
	counts = collections.Counter()
	try:
		if name.endswith(".tar"):
			try:
				with tarfile.open(fileobj=io.BufferedReader(stream, CHUNK), mode="r|") as archive:
					for member in archive:
						if member.isfile():
							store(
								member.name, lambda m=member: archive.extractfile(m).read(), counts
							)
			except tarfile.ReadError as exc:
				if stream.failed:
					raise zlib.error(f"inside tar: {exc}") from exc  # damaged entry, not a bad tar
				counts[f"broken_tar ({exc})"] += 1
		elif name.endswith(".zip"):
			# Year zips can be GBs: buffering one in RAM crashed the 2 GB Pi (2026-10-07),
			# so spill it to temp/ and open it from disk.
			spill = Path("/home/zruser/timelapse/temp") / f"seqzip-{Path(name).name}"
			cut_off = False
			try:
				with spill.open("wb") as out:
					try:
						while chunk := stream.read(CHUNK):
							out.write(chunk)
					except EOFError:
						# The outer zip ends inside this entry (webcam_insektenmuseum 2007.zip);
						# its front part is usually intact, so salvage it below.
						cut_off = True
				try:
					with zipfile.ZipFile(spill) as inner:
						for member in inner.infolist():
							if not member.is_dir():
								store(member.filename, lambda m=member: inner.read(m), counts)
				except zipfile.BadZipFile:
					salvage_local_entries(spill, counts)
			finally:
				spill.unlink(missing_ok=True)
			if cut_off:
				counts["outer_zip_cut_off_here"] += 1
				print(f"{name}: {dict(counts)}", flush=True)
				totals.update(counts)
				break
		elif not name.endswith("/"):
			store(name, lambda: io.BufferedReader(stream, CHUNK).read(), counts)
		stream.drain()
	except (EOFError, ValueError) as exc:
		print(f"{name}: stopped ({exc}) {dict(counts)}", flush=True)
		break
	except zlib.error as exc:
		# Damaged deflate data (webcam6_uferstrasse 2008): keep what was stored, then find the
		# next entry, since the sizes of this one are unknown without a central directory.
		counts[f"corrupt_entry ({exc})"] += 1
		print(f"{name}: {dict(counts)}", flush=True)
		totals.update(counts)
		raw.unread(stream.last_chunk)
		if not resync(raw, prefix):
			break
		continue
	raw.unread(stream.leftover)
	if not sized:
		# Data descriptor: optional signature, then crc + sizes (12 bytes, 20 for zip64).
		peek = raw.read(4)
		if struct.unpack("<I", peek)[0] != DESCRIPTOR:
			raw.unread(peek)
		raw.read(12)
		after = raw.read(4)
		if len(after) == 4 and struct.unpack("<I", after)[0] != LOCAL:
			raw.read(4)  # zip64: 8 more size bytes, 4 of them already read into `after`
			after = raw.read(4)
		raw.unread(after)
	if counts:
		print(f"{name}: {dict(counts)}", flush=True)
	totals.update(counts)

print(f"TOTAL: {dict(totals)}", flush=True)
if unknown_samples:
	print("unknown name samples:", *unknown_samples, sep="\n  ", flush=True)
