"""Regression: a short video with a fade-in must not produce an all-black QC sheet."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import cloud_runner as runner


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required for contact-sheet integration test")
class ContactSheet(unittest.TestCase):
    def test_short_fade_in_video_has_visible_samples(self):
        temporary_root = Path(__file__).resolve().parents[1] / ".cloud"
        temporary_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as temp:
            temp = Path(temp)
            video, sheet = temp / "fade.mp4", temp / "sheet.png"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=white:s=320x180:r=4:d=2",
                            "-vf", "fade=t=in:st=0:d=0.5", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
                           check=True, capture_output=True)
            with patch.object(runner, "LOG", temp / "private.log"):
                runner.make_final_sheet(video, sheet, total_frames=8, duration=2)
            pixels = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(sheet),
                                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
            self.assertGreater(max(pixels), 50, "QC sheet sampled only the black opening fade")


if __name__ == "__main__":
    unittest.main()
