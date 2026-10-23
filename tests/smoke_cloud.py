"""Real 1080p render -> encrypted segments -> copy concat -> soundtrack -> decrypt.

Requires npm ci, Playwright Chromium, FFmpeg, numpy, scipy and cryptography.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import cloud_runner as runner
from cloud_common import crypt_file, extract_archive, make_plan

KIT = Path(__file__).resolve().parents[1]


class CloudRenderSmoke(unittest.TestCase):
    def test_real_1080p_segments_audio_and_boundary_frames(self):
        (KIT / ".cloud").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=KIT / ".cloud") as temp:
            work = Path(temp)
            project, output = work / "project", work / "encrypted"
            for name in ("input", "story", "scenes", "build", "out"):
                (project / name).mkdir(parents=True)
            output.mkdir()
            cfg = {"resolution": "1080p", "aspect": "16:9", "fps": 4, "style": "dusk",
                   "voiceover": "input/voice.wav", "music": {"enabled": False}, "sfx": {"enabled": False},
                   "fadeIn": 0, "fadeOut": 0, "bars": "none"}
            (project / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
            (project / ".env").write_text("PRIVATE=must-not-be-served", encoding="utf-8")
            story = {"duration": 2, "shots": [{"id": "one", "start": 0, "end": 0.75},
                     {"id": "two", "start": 0.75, "end": 2, "in": {"type": "fade", "dur": 0.5}}]}
            (project / "story/shots.json").write_text(json.dumps(story), encoding="utf-8")
            (project / "scenes/shots.js").write_text("""
import { E, registerShot } from '/engine/core.js';
if ((await fetch('/project/.env')).status !== 404) throw new Error('Private files were exposed');
for (const [id, color] of [['one', '#ac4422'], ['two', '#2244ac']]) {
  registerShot(id, { draw(g, t, info) {
    g.fillStyle = color; g.fillRect(0, 0, E.W, E.H);
    g.fillStyle = '#ffeedd'; g.fillRect(info.globalT * 500, 300, 200, 200);
  }});
}
""", encoding="utf-8")
            with wave.open(str(project / "input/voice.wav"), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(48000)
                audio.writeframes(b"\0\0" * 96000)
            plan = make_plan(project, segment_seconds=1, workers=1)
            (work / "job.json").write_text(json.dumps(plan), encoding="utf-8")
            key = os.urandom(32)
            with patch.multiple(runner, WORK=work, OUTPUT=output, PROJECT=project, LOG=work / "private.log"):
                for index in range(2):
                    runner.render(argparse.Namespace(index=index), key)
                runner.merge(argparse.Namespace(parts=str(output)), key)
                crypt_file(output / "result.enc", work / "result.tar.gz", key, decrypt=True)
                extract_archive(work / "result.tar.gz", work / "result")
                final = work / "result/final.mp4"
                streams = runner.probe(final)
                video = next(s for s in streams if s["codec_type"] == "video")
                self.assertEqual((video["width"], video["height"], int(video["nb_read_frames"])), (1920, 1080, 8))
                self.assertTrue(any(s["codec_type"] == "audio" for s in streams))
                self.assertTrue((work / "result/final_sheet.png").exists())
                # Stream copy must preserve every decoded frame of each segment, including the seam.
                def hashes(path):
                    text = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-f", "framemd5", "-"], text=True)
                    return [line.rsplit(",", 1)[-1].strip() for line in text.splitlines() if not line.startswith("#")]
                expected = hashes(project / "build/part-0000.mp4") + hashes(project / "build/part-0001.mp4")
                self.assertEqual(hashes(final), expected)
                # The same global frame rendered from a fresh browser must match the segment's seam frame.
                fresh = project / "build/fresh.mp4"
                runner.run(["node", "render.mjs", "--project", project, "--from-frame", "4", "--to-frame", "5",
                            "--workers", "1", "--gl", "swiftshader", "--strict", "--crf", "0", "--out", fresh])
                baseline = project / "build/baseline.mp4"
                runner.run(["node", "render.mjs", "--project", project, "--workers", "1", "--gl", "swiftshader",
                            "--strict", "--crf", "0", "--out", baseline])
                self.assertEqual(hashes(fresh), [hashes(baseline)[4]])
                # Exercise every remote review path, including a non-zero preview audio offset.
                for mode in ("preview", "sheet", "styles", "stills"):
                    review = make_plan(project, mode=mode, start=0.25, end=1.5,
                                       workers=1, times="0.25,1", styles="dusk,midnight")
                    (work / "job.json").write_text(json.dumps(review), encoding="utf-8")
                    runner.render(argparse.Namespace(index=0), key)
                    crypt_file(output / "result.enc", work / "review.tar.gz", key, decrypt=True)
                    destination = work / mode
                    extract_archive(work / "review.tar.gz", destination)
                    expected = {"preview": "preview.mp4", "sheet": "sheets/sheet_01.png",
                                "styles": "styles/style_grid.png", "stills": "stills/sheet_01.png"}[mode]
                    self.assertTrue((destination / expected).exists())
                # Deliberately break a scene: strict cloud rendering must reject a seemingly valid error MP4.
                (project / "scenes/shots.js").write_text("throw new Error('private scene failure')", encoding="utf-8")
                with self.assertRaises(subprocess.CalledProcessError):
                    runner.run(["node", "render.mjs", "--project", project, "--workers", "1", "--strict"])


if __name__ == "__main__":
    unittest.main()
