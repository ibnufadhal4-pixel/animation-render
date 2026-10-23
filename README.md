# aiTrends — Encrypted Animation Render

Render animation projects on GitHub Actions while keeping project contents encrypted.
The public repository contains only the generic studio, examples and workflow.
Voiceovers, scripts, custom scene code, output videos and diagnostics travel encrypted
using AES-256-GCM. GitHub runners decrypt them temporarily to render.

## Use from your local studio

Requires Python 3.12+, GitHub CLI and `cryptography` locally. Chromium, Node packages,
FFmpeg, numpy and scipy for rendering are installed on the GitHub runners.

```bash
python -m pip install "cryptography>=44,<50"
gh auth login
python tools/cloud.py init --repo ibnufadhal4-pixel/animation-render
```

Keep `.cloud/key` backed up privately. On another computer, restore that key into
`.cloud/key` before running init; init will not replace an existing repository key
with a new one. Projects live in the ignored `projects/` directory. Include every
asset inside the project with relative paths.

```bash
python tools/cloud.py submit --project projects/my-video --mode sheet
python tools/cloud.py submit --project projects/my-video --mode preview --from 0 --to 30
python tools/cloud.py submit --project projects/my-video --mode final --segment-seconds 60
python tools/cloud.py status --job <job-id>
python tools/cloud.py fetch --job <job-id> --wait
```

Decrypted results are saved in `projects/my-video/out/<job-id>/`. Final jobs produce
`final.mp4` and `final_sheet.png`. The defaults are full project resolution (1080p
recommended), PNG frame capture, H.264 CRF 18, 60-second segments and up to 3 parallel
runners. Video is stream-copied when joining segments and muxing the full soundtrack.

For a synthetic test covering 2D, 3D and generated sound:

```bash
python tools/create_cloud_demo.py
python tools/cloud.py submit --project projects/cloud-verification --segment-seconds 3
```

## Failures and storage

Fetch private diagnostics with `python tools/cloud.py fetch --job <job-id> --diagnostics`.
Use **Re-run failed jobs** in Actions within 24 hours to reuse successful segments.
After checking and downloading the result, `python tools/cloud.py cleanup --job <job-id>`
removes the encrypted release input and workflow run/artifacts. Input releases persist
until cleanup; segment/debug artifacts expire after 1 day and final artifacts after
3 days. Public standard-runner compute is free under GitHub's current plan; storage
allowances still apply.

Public observers can see workflow source, job timing/status, segment counts and
encrypted file sizes. GitHub runners and trusted workflow editors are inside the
privacy boundary. Never commit `.cloud/key`, plaintext projects, or private logs.

See [cloud/README.md](cloud/README.md) for transport details and local verification.

## Live verification

The deployed workflow was tested on GitHub Actions with a segmented **1080p/24 FPS**
video containing 2D and 3D scenes, generated music and SFX. All 192 final frame hashes
matched the original segment frames, and the final and preview audio streams decoded
successfully. See [TESTING.md](TESTING.md) for run links, timings and reproduction steps.
