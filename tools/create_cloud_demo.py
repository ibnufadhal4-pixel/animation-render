"""Create a short synthetic 1080p/24fps project for a real GitHub Actions smoke test.

No narration files or transcription models are needed. The soundtrack uses a test tone,
generated music and SFX. Scenes cover 2D, a SwiftShader 3D orbit, and a blueprint chart.
"""
import argparse
import json
import math
from pathlib import Path
import shutil
import struct
import wave

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="cloud-verification")
    args = parser.parse_args()
    project = (ROOT / "projects" / args.name).resolve()
    if not project.is_relative_to(ROOT / "projects") or project == ROOT / "projects":
        raise ValueError("Choose a project name within projects/")
    project.mkdir(parents=True, exist_ok=False)
    for directory in ("input", "story", "timeline"):
        (project / directory).mkdir()
    shutil.copytree(ROOT / "examples/reaction-time/scenes", project / "scenes")
    cfg = {"title": "Cloud 1080p Verification", "aspect": "16:9", "resolution": "1080p", "fps": 24,
           "style": "dusk", "duration": 8, "voiceover": "input/test-tone.wav", "captions": False,
           "fadeIn": 0.15, "fadeOut": 0.3, "music": {"enabled": True, "gainDb": -20, "seed": 1},
           "sfx": {"enabled": True, "gainDb": -12}, "loudness": -14}
    story = {"duration": 8, "shots": [
        {"id": "s001", "start": 0, "end": 2, "line": "Synthetic 2D test", "in": {"type": "cut"}},
        {"id": "s008", "start": 2, "end": 5, "line": "Synthetic 3D test", "in": {"type": "fade", "dur": 0.4},
         "sfx": [{"at": 0.1, "name": "whoosh", "gain": -16}]},
        {"id": "s010", "start": 5, "end": 8, "line": "Synthetic chart test", "in": {"type": "fade", "dur": 0.4}}
    ], "music": [{"start": 0, "end": 8, "mood": "wonder", "intensity": 0.3}]}
    (project / "config.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    (project / "story/shots.json").write_text(json.dumps(story, indent=2) + "\n", encoding="utf-8")
    rate = 48000
    with wave.open(str(project / "input/test-tone.wav"), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        samples = bytearray()
        for index in range(rate * 8):
            t = index / rate
            envelope = min(1, t * 10, (8 - t) * 10) * (0.5 + 0.5 * math.sin(t * 2 * math.pi) ** 2)
            value = 0.12 * envelope * (math.sin(2 * math.pi * 440 * t) + 0.3 * math.sin(2 * math.pi * 660 * t))
            samples.extend(struct.pack("<h", round(32767 * value)))
        audio.writeframes(samples)
    print(f"Synthetic 8-second 1080p project ready: {project}")
    print(f"Submit: python tools/cloud.py submit --project projects/{args.name} --segment-seconds 3")


if __name__ == "__main__":
    main()
