"""tools/verify_kit.py — confirm every studio file was written exactly (run right after installing).

  python tools/verify_kit.py
Prints MISMATCH/MISSING for any file that differs from the tested version; copy those files again from the plugin kit folder.
(Line endings and leading/trailing blank lines are ignored. Files you customise later, e.g. engine/styles.js, will of course differ.)
"""
import hashlib, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPECTED = {
    ".gitignore": "b2aae9bcc4d7fcc4",
    "audio/dsp.py": "589d305d94d8acc3",
    "audio/mix.py": "5d36ee8ccf5e80be",
    "audio/music.py": "2fb3ce1df2fe5c7d",
    "audio/sfx.py": "2fa56141e2423718",
    "cloud/README.md": "63c1de572bddf95b",
    "cloud/render.yml": "54fb6bd278889e37",
    "cloud/finish.yml": "5d1e6005f04f60bd",
    "cloud/setup.sh": "86b320bff2423833",
    "cloud/requirements.txt": "9c5fd8079201d154",
    "engine/core.js": "cb84a01d65e347a9",
    "engine/fx2d.js": "d09f93f6d44366fa",
    "engine/player.js": "2efc90d6868b1472",
    "engine/rig2d.js": "ec2a665e0aa8ffed",
    "engine/styles.js": "66b00b1b5f87326f",
    "engine/three-kit.js": "02e249e302b95420",
    "engine/ui2d.js": "babd2978a5d2a6db",
    "examples/reaction-time/config.json": "9ee341c65b3cfe9a",
    "examples/reaction-time/scenes/cast.js": "e4faad3c508a5cf5",
    "examples/reaction-time/scenes/sets/cafe.js": "fb9adaa553e87b74",
    "examples/reaction-time/scenes/sets/lab.js": "a2da3ca0fff2d8c4",
    "examples/reaction-time/scenes/shots/01_cafe.js": "931e9c360ba052b3",
    "examples/reaction-time/scenes/shots/02_orbit3d.js": "77897bcae80a501e",
    "examples/reaction-time/scenes/shots/03_explain.js": "c22f0e7a8f505c78",
    "examples/reaction-time/story/bible.md": "e22b689a54461b41",
    "examples/reaction-time/story/shots.json": "9b1921e8e42c2498",
    "package.json": "1bd334931c9fa9de",
    "package-lock.json": "4d4896e47893f6b0",
    "player.html": "5ffdd7da4a48cd4b",
    "render.mjs": "4e6976799f2ce63b",
    "tests/test_cloud.py": "ccc89afcf41b9d1a",
    "tests/smoke_cloud.py": "5df6285ffe6182b2",
    "tests/test_contact_sheet.py": "c8a4c63cfb9ad045",
    "tests/verify_remote_run.py": "46a1a39951725fb3",
    "tests/test_mux_tail.py": "30283ab3b2f66de8",
    "tools/beats.py": "eb42a8aef4d87584",
    "tools/common.py": "e237321f2f12416e",
    "tools/cloud.py": "bc8169cd47159cca",
    "tools/cloud_common.py": "9f97bbfeb9b378a8",
    "tools/cloud_runner.py": "15ee66eba1698a83",
    "tools/create_cloud_demo.py": "e7dc92a1395a4ba5",
    "tools/doctor.py": "ce17e8e1bfcb9b86",
    "tools/new_project.py": "940758644aa95289",
    "tools/parse_script.py": "5163cf3162b2579b",
    "tools/transcribe.py": "7a306747b3100127",
}
bad = 0
for rel, want in EXPECTED.items():
    p = os.path.join(ROOT, *rel.split("/"))
    if not os.path.exists(p):
        print(f"MISSING   {rel}"); bad += 1; continue
    got = hashlib.sha256(open(p, "rb").read().replace(b"\r\n", b"\n").strip()).hexdigest()[:16]
    if got != want:
        print(f"MISMATCH  {rel} (expected {want}, got {got})"); bad += 1
print(f"{len(EXPECTED) - bad}/{len(EXPECTED)} files verified." + ("" if not bad else "  Copy the files listed above again from the plugin's kit folder, then run this again."))
sys.exit(1 if bad else 0)
