# Verified cloud deployment

Tested on **2026-10-23**, using renderer/workflow commit `99c708a` on GitHub-hosted
`ubuntu-24.04` runners. Inputs and artifacts were encrypted; results were fetched
and decrypted locally using the configured studio client.

## Final render

Successful run: https://github.com/ibnufadhal4-pixel/animation-render/actions/runs/39880838894

| Check | Result |
|---|---|
| Synthetic project | 8 seconds; 2D scene, SwiftShader 3D orbit, blueprint chart |
| Resolution / FPS | 1920×1080 / 24 FPS |
| Frame count | 192 |
| Segments | 3, with exclusive global frame ranges 0–72, 72–144, 144–192 |
| Joining fidelity | Every decoded final frame hash matches its original encrypted segment frame |
| Sound | Generated test tone, music and SFX; stereo AAC decodes without error |
| QC sheet | Three representative mid-video samples, visually inspected |
| End-to-end time | Approximately 3 minutes 57 seconds, including runner setup |

This is a short integration test, not a 5–10 minute production-video benchmark.

## Preview

Successful run: https://github.com/ibnufadhal4-pixel/animation-render/actions/runs/39880838873

The global range 1–3 seconds produced a **2-second, 960×540, 24 FPS** preview
containing 48 frames and stereo AAC audio. Both streams decode without errors.

## Automated checks

Nine local tests passed, covering authenticated encryption/tamper rejection,
safe extraction, exact frame coverage, client submission/download, key reuse,
and contact-sheet visibility for short videos with a black opening fade.
The kit manifest verified **43/43** files. Bash syntax and Actions workflow
validation passed before deployment.

Two issues found during live testing were fixed: contact-sheet sampling only the
black opening frame in a short clip, and slow Azure Ubuntu mirror downloads during
dependency installation. Runner setup now prefers available FFmpeg or a checksum-
verified static FFmpeg 8.1 build, and launches bundled headless Chromium against
the runner's existing shared libraries before attempting a bounded apt fallback.

## Reproduce

```bash
python -m unittest discover -s tests -p "test_*.py"
python tools/verify_kit.py
python tools/create_cloud_demo.py --name another-cloud-check
python tools/cloud.py submit --project projects/another-cloud-check --segment-seconds 3
python tools/cloud.py fetch --job <job-id> --wait
python tests/verify_remote_run.py --job <job-id>
```

The remote frame verifier needs FFmpeg locally for decoding/hashing and must run
before the segment artifacts expire (1 day). It does not render or encode locally.
