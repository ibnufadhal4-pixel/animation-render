"""A fractional voiceover end must not trim or retime the last copied video frame."""
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class MuxTail(unittest.TestCase):
    def test_fractional_audio_end_preserves_video_frames_and_fps(self):
        (ROOT / ".cloud").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / ".cloud") as directory:
            project = Path(directory)
            for folder in ("input", "build", "story", "out"):
                (project / folder).mkdir()
            duration, fps = 2.13, 24
            expected = math.ceil(duration * fps)
            with wave.open(str(project / "input/voice.wav"), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(48000)
                audio.writeframes(b"\0\0" * round(duration * 48000))
            (project / "config.json").write_text(json.dumps({"voiceover": "input/voice.wav", "title": "test",
                "music": {"enabled": False}, "sfx": {"enabled": False}}), encoding="utf-8")
            (project / "story/shots.json").write_text(json.dumps({"duration": duration, "shots": [{"start": 0, "end": duration}]}), encoding="utf-8")
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=24",
                            "-frames:v", str(expected), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(project / "build/video_silent.mp4")],
                           check=True, capture_output=True)
            subprocess.run([sys.executable, str(ROOT / "audio/mix.py"), "--project", str(project)], check=True, capture_output=True)
            output = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
                "-show_entries", "stream=nb_read_frames,avg_frame_rate", "-of", "json", str(project / "out/test.mp4")]))["streams"][0]
            self.assertEqual(int(output["nb_read_frames"]), expected)
            num, den = map(int, output["avg_frame_rate"].split("/"))
            self.assertAlmostEqual(num / den, fps, places=5)


if __name__ == "__main__":
    unittest.main()
