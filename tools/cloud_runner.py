"""GitHub runner entry points. Project output is captured in encrypted diagnostics only."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import traceback

from cloud_common import ROOT, archive_files, crypt_file, extract_archive, read_key

WORK = ROOT / ".cloud-run"
OUTPUT = ROOT / ".cloud-output"
PROJECT = WORK / "project"
LOG = WORK / "private.log"


def run(command):
    env = os.environ.copy()
    env.pop("AITRENDS_CLOUD_KEY", None)
    if command[0] != "gh":
        env.pop("GH_TOKEN", None)
        env.pop("GITHUB_TOKEN", None)
    with LOG.open("ab") as log:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env=env, check=True)


def probe(path):
    data = subprocess.check_output(["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-of", "json", str(path)], stderr=subprocess.PIPE)
    return json.loads(data)["streams"]


def check_video(path, frames, fps, audio=False):
    streams = probe(path)
    video = next(s for s in streams if s["codec_type"] == "video")
    num, den = map(int, video["avg_frame_rate"].split("/"))
    if int(video["nb_read_frames"]) != frames or not math.isclose(num / den, fps, abs_tol=0.00001):
        raise ValueError("Rendered video has wrong frame count or FPS")
    if video["codec_name"] != "h264" or video["pix_fmt"] != "yuv420p":
        raise ValueError("Unexpected video format")
    if audio and not any(s["codec_type"] == "audio" for s in streams):
        raise ValueError("Final video has no audio stream")
    return tuple(video.get(k) for k in ("codec_name", "width", "height", "pix_fmt", "time_base", "r_frame_rate", "profile", "level"))


def unpack(args, key):
    if not re.fullmatch(r"cloud-[a-f0-9]{32}", args.tag):
        raise ValueError("Invalid bundle tag")
    # GH_TOKEN is needed only for downloading this public release, not for scene execution.
    run(["gh", "release", "download", args.tag, "--repo", os.environ["GITHUB_REPOSITORY"],
         "--pattern", "input.enc", "--dir", WORK, "--clobber"])
    archive = WORK / "input.tar.gz"
    try:
        crypt_file(WORK / "input.enc", archive, key, decrypt=True)
        extract_archive(archive, WORK)
    finally:
        archive.unlink(missing_ok=True)
    # Only project code/visual customisations are overlaid; workflow/helpers stay public and fixed.
    shutil.copytree(WORK / "engine", ROOT / "engine", dirs_exist_ok=True)
    shutil.copyfile(WORK / "player.html", ROOT / "player.html")
    plan = json.loads((WORK / "job.json").read_text(encoding="utf-8"))
    if plan.get("version") != 1 or not 1 <= len(plan["segments"]) <= 240:
        raise ValueError("Invalid job plan")
    if args.plan:
        matrix = json.dumps({"index": list(range(len(plan["segments"])))}, separators=(",", ":"))
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
            out.write(f"matrix={matrix}\n")
        print(f"Prepared {len(plan['segments'])} segment(s).")


def render(args, key):
    plan = json.loads((WORK / "job.json").read_text(encoding="utf-8"))
    segment = plan["segments"][args.index]
    mode = plan["mode"]
    build = PROJECT / "build"
    build.mkdir(exist_ok=True)
    command = ["node", "render.mjs", "--project", PROJECT, "--gl", "swiftshader", "--workers", plan["workers"],
               "--threads", "2", "--scale", plan["scale"], "--format", "png", "--crf", "18", "--preset", "medium"]
    if mode in ("final", "preview"):
        video = build / "segment.mp4"
        command += ["--from-frame", segment["start"], "--to-frame", segment["end"], "--strict", "--out", video]
    elif mode == "sheet":
        command += ["--sheet"]
    elif mode == "styles":
        command += ["--styles", plan["styles"], "--at", plan["times"]]
    else:
        command += ["--stills", plan["times"]]
    print(f"Rendering segment {args.index + 1}/{len(plan['segments'])} ({mode}). Details are encrypted.", flush=True)
    run(command)
    if mode == "final":
        check_video(video, segment["end"] - segment["start"], plan["fps"])
        crypt_file(video, OUTPUT / f"part-{args.index:04d}.enc", key)
    else:
        if mode == "preview":
            # Mix the full global soundtrack once, then cut only the audio to the preview range.
            run([sys.executable, "audio/mix.py", "--project", PROJECT])
            preview = build / "preview.mp4"
            run(["ffmpeg", "-y", "-v", "error", "-i", video, "-ss", segment["start"] / plan["fps"],
                 "-i", build / "mix.wav", "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                 "-c:a", "aac", "-b:a", "192k", "-t", (segment["end"] - segment["start"]) / plan["fps"],
                 "-movflags", "+faststart", preview])
            check_video(preview, segment["end"] - segment["start"], plan["fps"], audio=True)
        package_result(key, mode)
    print("Encrypted output ready.", flush=True)


def package_result(key, mode):
    result = WORK / "result.tar.gz"
    with tarfile.open(result, "w:gz") as archive:
        if mode == "final":
            archive.add(PROJECT / "out/final.mp4", arcname="final.mp4")
            archive.add(PROJECT / "build/final_sheet.png", arcname="final_sheet.png")
        elif mode == "preview":
            archive.add(PROJECT / "build/preview.mp4", arcname="preview.mp4")
        else:
            folder = {"sheet": "sheets", "styles": "styles", "stills": "stills"}[mode]
            archive_files(archive, PROJECT / "build" / folder, folder)
    try:
        crypt_file(result, OUTPUT / "result.enc", key)
    finally:
        result.unlink(missing_ok=True)


def make_final_sheet(video, destination, total_frames, duration):
    # Midpoints avoid sampling only the opening fade on short videos. At most 60 tiles.
    count = min(total_frames, 60, max(3, math.ceil(duration / 10)))
    indices = [min(total_frames - 1, int((index + 0.5) * total_frames / count)) for index in range(count)]
    select = "+".join(f"eq(n\\,{index})" for index in indices)
    columns = min(6, count)
    filters = f"select={select},scale=320:-1,tile={columns}x{math.ceil(count / columns)}"
    run(["ffmpeg", "-y", "-v", "error", "-i", video, "-vf", filters,
         "-frames:v", "1", destination])


def merge(args, key):
    plan = json.loads((WORK / "job.json").read_text(encoding="utf-8"))
    if plan["mode"] != "final":
        # Non-final modes already produced their encrypted result in the single segment job.
        return
    build = PROJECT / "build"
    build.mkdir(exist_ok=True)
    parts = []
    expected_format = None
    for index, segment in enumerate(plan["segments"]):
        part = build / f"part-{index:04d}.mp4"
        crypt_file(Path(args.parts) / f"part-{index:04d}.enc", part, key, decrypt=True)
        fmt = check_video(part, segment["end"] - segment["start"], plan["fps"])
        if expected_format is not None and fmt != expected_format:
            raise ValueError("Segment formats disagree")
        expected_format = fmt
        parts.append(part)
    listing = build / "concat.txt"
    listing.write_text("\n".join(f"file '{p.name}'" for p in parts) + "\n", encoding="utf-8")
    silent = build / "video_silent.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", listing,
         "-map", "0:v:0", "-c", "copy", "-movflags", "+faststart", silent])
    check_video(silent, plan["total_frames"], plan["fps"])
    final = PROJECT / "out/final.mp4"
    run([sys.executable, "audio/mix.py", "--project", PROJECT, "--out", final])
    check_video(final, plan["total_frames"], plan["fps"], audio=True)
    make_final_sheet(final, build / "final_sheet.png", plan["total_frames"], plan["duration"])
    package_result(key, "final")
    print("Segments joined without video re-encoding; audio and frame-count checks passed.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["unpack", "render", "merge", "diagnostics"])
    ap.add_argument("--tag")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--index", type=int, default=0)
    ap.add_argument("--parts", default=".cloud-parts")
    ap.add_argument("--label", default="job")
    args = ap.parse_args()
    WORK.mkdir(exist_ok=True)
    OUTPUT.mkdir(exist_ok=True)
    key = read_key(os.environ.get("AITRENDS_CLOUD_KEY", ""))
    try:
        if args.command == "diagnostics":
            if LOG.exists():
                if not re.fullmatch(r"[a-z0-9-]+", args.label):
                    raise ValueError("Invalid diagnostics label")
                crypt_file(LOG, OUTPUT / f"debug-{args.label}.enc", key)
        else:
            {"unpack": unpack, "render": render, "merge": merge}[args.command](args, key)
    except Exception:
        with LOG.open("a", encoding="utf-8") as out:
            traceback.print_exc(file=out)
        print("Cloud step failed. Fetch encrypted diagnostics locally for details.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
