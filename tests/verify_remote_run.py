"""Verify a fetched final cloud job against its original encrypted video segments.

Usage: python tests/verify_remote_run.py --job cloud-<id>
Requires FFmpeg locally, plus the original .cloud/key and job state. It decodes
frames to hashes; it does not render animation or re-encode the video.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import cloud
from cloud_common import crypt_file
from cloud_runner import check_video, probe


def frame_hashes(path):
    result = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0",
                                      "-f", "framemd5", "-"], text=True, stderr=subprocess.PIPE)
    return [line.rsplit(",", 1)[-1].strip() for line in result.splitlines() if line and not line.startswith("#")]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True)
    args = parser.parse_args()
    state_path, state = cloud.job_state(args.job)
    work = state_path.parent
    video = Path(state["project"]) / "out" / args.job / "final.mp4"
    with tempfile.TemporaryDirectory(dir=work) as temp:
        temp = Path(temp)
        crypt_file(work / "input.enc", temp / "input.tar.gz", cloud.key(), decrypt=True)
        with tarfile.open(temp / "input.tar.gz", "r:gz") as archive:
            plan = json.load(archive.extractfile("job.json"))
        if plan["mode"] != "final":
            raise ValueError("This verifier checks final jobs with separate video segment artifacts")
        cloud.gh("run", "download", state["run_id"], "--repo", state["repo"], "--pattern", "cloud-part-*",
                 "--dir", str(temp / "segments"))
        expected = []
        for index, segment in enumerate(plan["segments"]):
            encrypted = temp / "segments" / f"cloud-part-{index}" / f"part-{index:04d}.enc"
            part = temp / f"part-{index:04d}.mp4"
            crypt_file(encrypted, part, cloud.key(), decrypt=True)
            check_video(part, segment["end"] - segment["start"], plan["fps"])
            expected.extend(frame_hashes(part))
        check_video(video, plan["total_frames"], plan["fps"], audio=True)
        if frame_hashes(video) != expected:
            raise ValueError("Decoded final frames differ from the original segment frames")
    # Decode audio too, so a broken AAC stream cannot pass a metadata-only check.
    subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(video), "-map", "0:a:0",
                    "-f", "null", "-"], check=True, capture_output=True)
    streams = probe(video)
    image = next(s for s in streams if s["codec_type"] == "video")
    audio = next(s for s in streams if s["codec_type"] == "audio")
    report = {"run_url": f"https://github.com/{state['repo']}/actions/runs/{state['run_id']}",
              "width": image["width"], "height": image["height"], "fps": plan["fps"],
              "frames": len(expected), "segments": len(plan["segments"]),
              "audio_codec": audio["codec_name"], "audio_channels": audio["channels"],
              "all_final_frames_match_segments": True, "audio_decodes": True}
    cloud.save_json(work / "verification.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
