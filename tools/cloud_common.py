"""Cloud transport: streaming authenticated encryption and portable, safe archives."""
import base64
import json
import math
import os
from pathlib import Path, PurePosixPath
import tarfile
import tempfile

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"AITRENDS-CLOUD-1\0"
CHUNK = 1024 * 1024
ROOT = Path(__file__).resolve().parents[1]


def read_key(value):
    try:
        key = base64.b64decode(value.strip(), altchars=b"-_", validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid cloud key") from exc
    if len(key) != 32:
        raise ValueError("Cloud key must contain 32 random bytes")
    return key


def crypt_file(source, destination, key, decrypt=False):
    """Authenticate header + ciphertext. Publish plaintext only after tag verification."""
    source, destination = Path(source), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=destination.parent, prefix=".partial-")
    try:
        with os.fdopen(fd, "wb") as out, source.open("rb") as inp:
            if decrypt:
                header = inp.read(len(MAGIC) + 12)
                if not header.startswith(MAGIC) or len(header) != len(MAGIC) + 12:
                    raise ValueError("Invalid encrypted cloud file")
                size = source.stat().st_size - len(header) - 16
                if size < 0:
                    raise ValueError("Truncated encrypted cloud file")
                inp.seek(-16, os.SEEK_END)
                cipher = Cipher(algorithms.AES(key), modes.GCM(header[-12:], inp.read(16))).decryptor()
                inp.seek(len(header))
            else:
                header = MAGIC + os.urandom(12)
                cipher = Cipher(algorithms.AES(key), modes.GCM(header[-12:])).encryptor()
                out.write(header)
                size = source.stat().st_size
            cipher.authenticate_additional_data(header)
            while size:
                block = inp.read(min(CHUNK, size))
                if not block:
                    raise ValueError("Truncated cloud file")
                size -= len(block)
                out.write(cipher.update(block))
            out.write(cipher.finalize())
            if not decrypt:
                out.write(cipher.tag)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


def archive_files(archive, directory, prefix, excluded=()):
    directory = Path(directory)
    for item in sorted(directory.rglob("*")):
        rel = item.relative_to(directory)
        if any(p in excluded or p.startswith(".") for p in rel.parts):
            continue
        if item.is_symlink():
            raise ValueError("Put actual asset files inside the project, not symlinks")
        if item.is_file():
            archive.add(item, arcname=f"{prefix}/{rel.as_posix()}", recursive=False)


def extract_archive(source, destination):
    """Reject links, devices, duplicate paths, Windows paths and traversal on every OS."""
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(source, "r:gz") as archive:
        members = archive.getmembers()
        seen = set()
        for member in members:
            name = member.name
            path = PurePosixPath(name)
            if (not name or "\\" in name or ":" in name or path.is_absolute()
                    or ".." in path.parts or not (member.isfile() or member.isdir())):
                raise ValueError("Unsafe archive member")
            target = destination.joinpath(*path.parts).resolve()
            if not target.is_relative_to(destination) or target in seen:
                raise ValueError("Unsafe or duplicate archive path")
            seen.add(target)
        # data filter also normalises permissions; Python >= 3.12 is required for cloud tools.
        archive.extractall(destination, members=members, filter="data")


def make_plan(project, mode="final", segment_seconds=60, workers=2,
              start=0, end=None, scale=None, times="1", styles="dusk,midnight,golden,neon,storybook",
              model="small", language=None):
    project = Path(project)
    cfg = json.loads((project / "config.json").read_text(encoding="utf-8"))
    if mode == "transcribe":
        duration = cfg.get("duration")
        if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
            raise ValueError("Transcription needs a positive config.duration")
        voice = (project / cfg["voiceover"]).resolve()
        if not voice.is_relative_to(project.resolve()) or not voice.is_file():
            raise ValueError("Voiceover must be a file inside the project")
        if model not in ("tiny", "base", "small", "medium", "large-v3"):
            raise ValueError("Invalid Whisper model")
        if language is not None and (not language.isalpha() or len(language) not in (2, 3)):
            raise ValueError("Use a two/three-letter language code, or omit it for detection")
        return {"version": 1, "mode": mode, "duration": duration, "model": model,
                "language": language, "segments": [{"start": 0, "end": duration}]}
    story = json.loads((project / "story/shots.json").read_text(encoding="utf-8"))
    if not story.get("shots"):
        raise ValueError("Project needs a shot list")
    duration = story.get("duration") or story["shots"][-1]["end"]
    fps = cfg.get("fps", 24)
    if not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in (duration, fps, segment_seconds)):
        raise ValueError("Duration, fps and segment length must be positive")
    if abs(story["shots"][-1]["end"] - duration) > 1 / fps:
        raise ValueError("Story duration and last shot end disagree")
    if not isinstance(workers, int) or not 1 <= workers <= 4:
        raise ValueError("Cloud workers must be between 1 and 4")
    if mode not in ("final", "preview", "sheet", "styles", "stills"):
        raise ValueError("Invalid render mode")
    total = math.ceil(duration * fps)
    if mode == "final":
        frames = max(1, round(segment_seconds * fps))
        segments = [{"start": a, "end": min(a + frames, total)} for a in range(0, total, frames)]
    else:
        if not math.isfinite(start) or start < 0 or (end is not None and not math.isfinite(end)):
            raise ValueError("Invalid preview range")
        a, b = round(start * fps), min(total, round((end if end is not None else min(duration, start + 30)) * fps))
        if a >= b:
            raise ValueError("Preview range is empty")
        segments = [{"start": a, "end": b}]
    if len(segments) > 240:
        raise ValueError("Too many segments; increase --segment-seconds")
    if scale is None:
        scale = 1 if mode == "final" else 0.5
    if not math.isfinite(scale) or not 0 < scale <= 1 or (mode == "final" and scale != 1):
        raise ValueError("Final renders use full resolution; other scales must be in (0, 1]")
    if mode in ("styles", "stills"):
        points = [float(t) for t in times.split(",")]
        if not points or any(not math.isfinite(t) or t < 0 or t >= duration for t in points):
            raise ValueError("Still times must lie within the video")
    return {"version": 1, "mode": mode, "fps": fps, "total_frames": total, "duration": duration,
            "workers": workers, "scale": scale, "times": times, "styles": styles, "segments": segments}
