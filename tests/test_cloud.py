"""Tests for the privacy and frame-boundary contracts of the cloud pipeline."""
import base64
import io
import json
import math
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import argparse
import contextlib
import shutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from cloud_common import CHUNK, crypt_file, extract_archive, make_plan, read_key
import cloud


class CloudContracts(unittest.TestCase):
    def setUp(self):
        temporary_root = Path(__file__).resolve().parents[1] / ".cloud"
        temporary_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temporary_root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.key = os.urandom(32)

    def test_streaming_roundtrip_and_random_nonces(self):
        source = self.root / "voiceover.bin"
        source.write_bytes(os.urandom(CHUNK + 17))
        a, b, out = (self.root / n for n in ("a.enc", "b.enc", "out.bin"))
        crypt_file(source, a, self.key)
        crypt_file(source, b, self.key)
        self.assertNotEqual(a.read_bytes(), b.read_bytes())
        crypt_file(a, out, self.key, decrypt=True)
        self.assertEqual(source.read_bytes(), out.read_bytes())
        self.assertEqual(read_key(base64.urlsafe_b64encode(self.key).decode()), self.key)

    def test_authentication_never_publishes_partial_plaintext(self):
        source, encrypted, out = (self.root / n for n in ("source", "input.enc", "result"))
        source.write_bytes(b"private script" * 100)
        crypt_file(source, encrypted, self.key)
        original = encrypted.read_bytes()
        for payload in (original[:-1], original[:40] + bytes([original[40] ^ 1]) + original[41:]):
            encrypted.write_bytes(payload)
            out.write_bytes(b"previous good result")
            with self.assertRaises(Exception):
                crypt_file(encrypted, out, self.key, decrypt=True)
            self.assertEqual(out.read_bytes(), b"previous good result")
            self.assertFalse(list(self.root.glob(".partial-*")))
        encrypted.write_bytes(original)
        with self.assertRaises(Exception):
            crypt_file(encrypted, out, os.urandom(32), decrypt=True)
        self.assertEqual(out.read_bytes(), b"previous good result")

    def test_archive_rejects_traversal_windows_paths_and_links(self):
        for name in ("../escape", "/absolute", "C:/escape", "a\\..\\escape", "safe/link"):
            archive = self.root / "input.tar.gz"
            with tarfile.open(archive, "w:gz") as out:
                member = tarfile.TarInfo(name)
                if name.endswith("link"):
                    member.type, member.linkname = tarfile.SYMTYPE, "../../escape"
                else:
                    member.size = 6
                out.addfile(member, io.BytesIO(b"secret"))
            with self.assertRaises(ValueError):
                extract_archive(archive, self.root / "extracted")
        self.assertFalse((self.root / "escape").exists())

    def test_safe_archive_is_portable(self):
        archive = self.root / "input.tar.gz"
        with tarfile.open(archive, "w:gz") as out:
            member = tarfile.TarInfo("project/input/voiceover.wav")
            member.size = 5
            out.addfile(member, io.BytesIO(b"audio"))
        extract_archive(archive, self.root / "result")
        self.assertEqual((self.root / "result/project/input/voiceover.wav").read_bytes(), b"audio")

    def project(self, duration, fps):
        (self.root / "story").mkdir(exist_ok=True)
        (self.root / "config.json").write_text(json.dumps({"fps": fps}), encoding="utf-8")
        (self.root / "story/shots.json").write_text(json.dumps({"duration": duration, "shots": [{"start": 0, "end": duration}]}), encoding="utf-8")
        return self.root

    def test_segments_cover_each_frame_once_including_fractional_tail(self):
        for duration, fps in ((300, 24), (600.13, 24), (333.7, 23.976), (0.17, 24)):
            plan = make_plan(self.project(duration, fps))
            segments = plan["segments"]
            self.assertEqual(segments[0]["start"], 0)
            self.assertEqual(segments[-1]["end"], math.ceil(duration * fps))
            for left, right in zip(segments, segments[1:]):
                self.assertEqual(left["end"], right["start"])
            self.assertEqual(sum(s["end"] - s["start"] for s in segments), plan["total_frames"])

    def test_preview_preserves_global_offset_and_final_cannot_downscale(self):
        project = self.project(600, 24)
        plan = make_plan(project, mode="preview", start=60.25, end=90)
        self.assertEqual(plan["segments"], [{"start": 1446, "end": 2160}])
        with self.assertRaises(ValueError):
            make_plan(project, scale=0.5)
        with self.assertRaises(ValueError):
            make_plan(project, mode="preview", start=100, end=90)
        with self.assertRaises(ValueError):
            make_plan(project, segment_seconds=0.1)

    def test_client_uploads_only_encrypted_snapshot_and_fetches_private_result(self):
        studio = self.root / "studio"
        for folder in ("engine", "cloud", "projects/private-title/story", "projects/private-title/input", "projects/private-title/build"):
            (studio / folder).mkdir(parents=True, exist_ok=True)
        project = studio / "projects/private-title"
        (project / "config.json").write_text(json.dumps({"fps": 24}), encoding="utf-8")
        (project / "story/shots.json").write_text(json.dumps({"duration": 10, "shots": [{"start": 0, "end": 10}]}), encoding="utf-8")
        (project / "input/script.txt").write_text("private dialogue", encoding="utf-8")
        (project / "build/old.mp4").write_bytes(b"stale render")
        (studio / "engine/custom.js").write_text("private style", encoding="utf-8")
        (studio / "player.html").write_text("player", encoding="utf-8")
        (studio / "cloud/render.yml").write_text("workflow template", encoding="utf-8")
        local = studio / ".cloud"
        calls = []
        release = {}

        def fake_gh(*args, input=None):
            calls.append(args)
            if args[0] == "api":
                return json.dumps({"default_branch": "main"})
            if args[:2] == ("secret", "list"):
                return "[]"
            if args[:2] == ("secret", "set"):
                self.assertEqual(len(read_key(input)), 32)
            if args[:2] == ("release", "create"):
                release["tag"] = args[2]
                release["encrypted"] = Path(args[3]).read_bytes()
                self.assertNotIn(b"private dialogue", release["encrypted"])
                self.assertNotIn("private-title", " ".join(map(str, args)))
            if args[:2] == ("run", "list"):
                return json.dumps([{"databaseId": 42, "displayTitle": f"Cloud render {release['tag']}"}])
            if args[:2] == ("run", "view"):
                return json.dumps({"status": "completed", "conclusion": "success"})
            if args[:2] == ("run", "download"):
                shutil.copyfile(self.root / "result.enc", Path(args[args.index("--dir") + 1]) / "result.enc")
            return ""

        with patch.multiple(cloud, ROOT=studio, LOCAL=local), patch.object(cloud, "gh", side_effect=fake_gh), contextlib.redirect_stdout(io.StringIO()):
            cloud.init(argparse.Namespace(repo="owner/render", update_workflow=False))
            first_key = (local / "key").read_bytes()
            cloud.init(argparse.Namespace(repo="owner/render", update_workflow=False))
            self.assertEqual((local / "key").read_bytes(), first_key)
            args = cloud.parser().parse_args(["submit", "--project", str(project)])
            cloud.submit(args)
            job = release["tag"]
            encrypted = local / "jobs" / job / "input.enc"
            archive = self.root / "snapshot.tar.gz"
            crypt_file(encrypted, archive, cloud.key(), decrypt=True)
            extract_archive(archive, self.root / "snapshot")
            self.assertEqual((self.root / "snapshot/project/input/script.txt").read_text(), "private dialogue")
            self.assertEqual((self.root / "snapshot/engine/custom.js").read_text(), "private style")
            self.assertFalse((self.root / "snapshot/project/build").exists())
            with tarfile.open(self.root / "result.tar.gz", "w:gz") as archive:
                member = tarfile.TarInfo("final.mp4")
                member.size = 5
                archive.addfile(member, io.BytesIO(b"video"))
            crypt_file(self.root / "result.tar.gz", self.root / "result.enc", cloud.key())
            cloud.fetch(argparse.Namespace(job=job, wait=False, diagnostics=False))
            self.assertEqual((project / "out" / job / "final.mp4").read_bytes(), b"video")
            self.assertTrue((project / "build/old.mp4").exists())
            with self.assertRaises(ValueError):
                cloud.fetch(argparse.Namespace(job=job, wait=False, diagnostics=False))
        self.assertTrue(any(args[:2] == ("workflow", "run") for args in calls))

    def test_existing_remote_key_is_not_silently_rotated_on_new_machine(self):
        local = self.root / ".cloud"
        def fake_gh(*args, input=None):
            if args[0] == "api":
                return '{"default_branch":"main"}'
            if args[:2] == ("secret", "list"):
                return '[{"name":"AITRENDS_CLOUD_KEY"}]'
            self.fail("Existing secret must not be overwritten")
        with patch.multiple(cloud, ROOT=self.root, LOCAL=local), patch.object(cloud, "gh", side_effect=fake_gh):
            with self.assertRaisesRegex(ValueError, "Restore the original"):
                cloud.init(argparse.Namespace(repo="owner/render", update_workflow=False))
        self.assertFalse((local / "key").exists())


if __name__ == "__main__":
    unittest.main()
