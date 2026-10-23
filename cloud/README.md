# Encrypted GitHub Actions rendering

This directory's `render.yml` is a workflow **template**. `tools/cloud.py init` installs it at `.github/workflows/render-cloud.yml` in the **standalone studio repository root** (the directory containing `render.mjs`). Publishing the plugin folder itself does not install a runnable workflow.

See the plugin's `references/cloud-render.md` for setup and the agent workflow. Client commands:

```bash
python tools/cloud.py init --repo OWNER/REPO
python tools/cloud.py submit --project projects/my-video --mode sheet
python tools/cloud.py submit --project projects/my-video --mode preview --from 0 --to 30
python tools/cloud.py submit --project projects/my-video --mode final --segment-seconds 60
python tools/cloud.py status --job cloud-JOB_ID
python tools/cloud.py fetch --job cloud-JOB_ID --wait
python tools/cloud.py fetch --job cloud-JOB_ID --diagnostics
python tools/cloud.py cleanup --job cloud-JOB_ID
```

`cloud-JOB_ID` denotes the full `cloud-` + 32-hex ID printed by submit. All commands run inside the studio. Python 3.12+, `cryptography`, GitHub CLI and GitHub authentication are needed locally. Rendering and audio dependencies are installed on runners.

Inputs are streamed through AES-256-GCM with a fresh 96-bit nonce per file. The random 256-bit key lives in ignored `.cloud/key` and repository secret `AITRENDS_CLOUD_KEY`. Authenticated decryption completes before a file is published or extracted. No password is accepted or passed on a command line. Only encrypted release attachments, video segments, results and diagnostic logs are uploaded. Release attachments remain until explicit cleanup; artifacts expire after 1 day (parts/debug) or 3 days (final result).

For 5–10 minute 1080p projects the defaults are 60-second segments, 2 Chromium workers per runner, at most 3 parallel runners, PNG capture and H.264 CRF 18/medium. Every segment keeps the project's global frame indices. Concatenation and soundtrack mux both stream-copy video. Identical render settings prevent quality loss from an additional encode; separate encodes can still differ from a monolithic encode at GOP boundaries. Scenes must calculate animation from time and seeded randomness, rather than accumulated state.

Only the renderer and public workflow are committed. The encrypted snapshot includes project files (excluding hidden files, build, out and dependency caches), engine customisations and player HTML. Keep all asset references project-relative; external absolute paths are not portable. Workflow/tools/audio changes must be published to the studio repository; they are not injected from the private project. Preserve `.cloud/key` privately to decrypt old results. Re-running init reuses that key.

On failure, use GitHub's **Re-run failed jobs** within 24 hours to reuse successful segment artifacts. Re-running the entire workflow renders everything again. Fetch encrypted diagnostics for the failing segment and inspect locally; after editing a scene, submit a new job. No cross-job stale segment cache is used. Clean up each job after downloading and checking its result.

Privacy boundaries: public observers can see workflow code, run timing/status, segment counts, encrypted file sizes and encrypted packages. GitHub's runner decrypts the project to render it. Repository collaborators who can edit workflows or access secrets are trusted. Do not print decrypted diagnostics in public logs/issues or add plaintext project files to Git history. Encryption does not remove previously published files.

Standard hosted Linux runner compute is free for public repositories under GitHub's current plan; artifact storage and execution/concurrency limits still apply. This is batch rendering, not a persistent server. Keep artifact retention short and remove completed jobs rather than using Actions as a video archive.

## Verification

```bash
python -m unittest discover -s tests -p "test_cloud*.py"
# Optional real Chromium + FFmpeg + audio smoke test:
python -m unittest discover -s tests -p "smoke_cloud*.py"
```
