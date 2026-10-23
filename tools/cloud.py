"""Encrypted GitHub Actions client. Run `python tools/cloud.py --help` from the studio."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid

from cloud_common import ROOT, archive_files, crypt_file, extract_archive, make_plan, read_key

LOCAL = ROOT / ".cloud"
WORKFLOW = "render-cloud.yml"


def gh(*args, input=None):
    result = subprocess.run(["gh", *map(str, args)], input=input, capture_output=True, text=True)
    if result.returncode:
        # gh diagnostics are useful locally; keys are passed on stdin, never in arguments.
        raise RuntimeError(result.stderr.strip() or "GitHub CLI failed")
    return result.stdout.strip()


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def settings():
    path = LOCAL / "config.json"
    if not path.exists():
        raise ValueError("Run `python tools/cloud.py init --repo OWNER/REPO` first")
    return json.loads(path.read_text(encoding="utf-8"))


def key():
    return read_key((LOCAL / "key").read_text(encoding="ascii"))


def init(args):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        raise ValueError("Repository must be OWNER/REPO")
    # Check auth and repository before writing credentials.
    repo = json.loads(gh("api", f"repos/{args.repo}"))
    if repo.get("archived"):
        raise ValueError("Repository is archived")
    LOCAL.mkdir(exist_ok=True)
    # The ignore file must exist before a key or project is staged for publication.
    ignore = ROOT / ".gitignore"
    required = ["/projects/", "/.cloud/", "/.cloud-run/", "/.cloud-output/", "/node_modules/"]
    text = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
    missing = [line for line in required if line not in text.splitlines()]
    if missing:
        ignore.write_text(text.rstrip() + "\n" + "\n".join(missing) + "\n", encoding="utf-8")
    key_path = LOCAL / "key"
    if not key_path.exists():
        secrets = json.loads(gh("secret", "list", "--repo", args.repo, "--json", "name"))
        if any(secret["name"] == "AITRENDS_CLOUD_KEY" for secret in secrets):
            raise ValueError("Repository already has a cloud key. Restore the original .cloud/key from your private backup first")
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as out:
            out.write(base64.urlsafe_b64encode(os.urandom(32)).decode() + "\n")
    read_key(key_path.read_text(encoding="ascii"))
    gh("secret", "set", "AITRENDS_CLOUD_KEY", "--repo", args.repo, input=key_path.read_text(encoding="ascii"))
    destination = ROOT / ".github/workflows" / WORKFLOW
    template = ROOT / "cloud/render.yml"
    if destination.exists() and destination.read_bytes() != template.read_bytes() and not args.update_workflow:
        raise ValueError("Workflow already differs; use --update-workflow to replace it after review")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template, destination)
    save_json(LOCAL / "config.json", {"repo": args.repo, "ref": repo["default_branch"]})
    print("Cloud setup ready. Keep .cloud/key backed up privately; it decrypts your results.")
    print("Publish the studio files and .github/workflows/render-cloud.yml to the repository default branch.")
    print("Projects and .cloud are excluded by .gitignore. Check staged files before publishing.")


def job_state(identifier):
    if not re.fullmatch(r"cloud-[a-f0-9]{32}", identifier):
        raise ValueError("Invalid cloud job ID")
    path = LOCAL / "jobs" / identifier / "state.json"
    return path, json.loads(path.read_text(encoding="utf-8"))


def find_run(state, attempts=1):
    if state.get("run_id"):
        return state["run_id"]
    for attempt in range(attempts):
        runs = json.loads(gh("run", "list", "--repo", state["repo"], "--workflow", WORKFLOW,
                            "--limit", "100", "--json", "databaseId,displayTitle"))
        for run in runs:
            if run["displayTitle"] == f"Cloud render {state['job']}":
                return run["databaseId"]
        if attempt + 1 < attempts:
            time.sleep(3)
    raise ValueError("Run has not appeared yet; retry status shortly (or check GitHub Actions)")


def submit(args):
    cfg = settings()
    # Fail before uploading if the workflow has not been published/enabled.
    gh("workflow", "view", WORKFLOW, "--repo", cfg["repo"])
    project = Path(args.project).resolve()
    if not project.is_dir() or not project.is_relative_to(ROOT / "projects"):
        raise ValueError("Store the project inside this studio's projects/ folder")
    plan = make_plan(project, args.mode, args.segment_seconds, args.workers,
                     args.start, args.end, args.scale, args.times, args.styles)
    identifier = "cloud-" + uuid.uuid4().hex
    work = LOCAL / "jobs" / identifier
    work.mkdir(parents=True)
    state = {"job": identifier, "repo": cfg["repo"], "ref": cfg["ref"], "project": str(project), "mode": args.mode}
    save_json(work / "state.json", state)
    print(f"Job: {identifier}")
    print(f"Preparing {len(plan['segments'])} segment(s); project contents stay encrypted.")
    with tempfile.TemporaryDirectory(dir=work) as temp:
        temp = Path(temp)
        save_json(temp / "job.json", plan)
        archive_path = temp / "input.tar.gz"
        with tarfile.open(archive_path, "w:gz") as archive:
            archive.add(temp / "job.json", arcname="job.json")
            archive_files(archive, project, "project", excluded=("build", "out", "node_modules", "__pycache__"))
            # Include private custom styles/engine changes, not just the public defaults.
            archive_files(archive, ROOT / "engine", "engine", excluded=("__pycache__",))
            archive.add(ROOT / "player.html", arcname="player.html")
        crypt_file(archive_path, work / "input.enc", key())
    gh("release", "create", identifier, str(work / "input.enc"), "--repo", cfg["repo"],
       "--target", cfg["ref"], "--prerelease", "--title", identifier,
       "--notes", "Encrypted render input. Only the encryption key can open this package.")
    gh("workflow", "run", WORKFLOW, "--repo", cfg["repo"], "--ref", cfg["ref"],
       "--field", f"bundle_tag={identifier}")
    try:
        state["run_id"] = find_run(state, attempts=20)
        save_json(work / "state.json", state)
        print(f"https://github.com/{cfg['repo']}/actions/runs/{state['run_id']}")
    except ValueError as exc:
        print(str(exc))
    print(f"Check: python tools/cloud.py status --job {identifier}")
    print(f"Fetch: python tools/cloud.py fetch --job {identifier} --wait")


def status(args):
    path, state = job_state(args.job)
    state["run_id"] = find_run(state)
    save_json(path, state)
    run = json.loads(gh("run", "view", state["run_id"], "--repo", state["repo"],
                        "--json", "status,conclusion,url,jobs"))
    print(f"{run['status']} {run['conclusion'] or ''}\n{run['url']}")
    for job in run["jobs"]:
        print(f"  {job['name']}: {job['conclusion'] or job['status']}")


def fetch(args):
    state_path, state = job_state(args.job)
    state["run_id"] = find_run(state)
    save_json(state_path, state)
    if args.wait:
        gh("run", "watch", state["run_id"], "--repo", state["repo"], "--interval", "20")
    work = state_path.parent
    if args.diagnostics:
        destination = work / "diagnostics"
        destination.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as temp:
            gh("run", "download", state["run_id"], "--repo", state["repo"], "--pattern", "cloud-debug-*", "--dir", temp)
            for encrypted in Path(temp).rglob("*.enc"):
                crypt_file(encrypted, destination / (encrypted.stem + ".txt"), key(), decrypt=True)
        print(f"Private diagnostics: {destination}")
        return
    run = json.loads(gh("run", "view", state["run_id"], "--repo", state["repo"], "--json", "status,conclusion"))
    if run["status"] != "completed" or run["conclusion"] != "success":
        raise ValueError("Render is unfinished or failed. Check status; fetch --diagnostics decrypts private logs")
    with tempfile.TemporaryDirectory(dir=work) as temp:
        temp = Path(temp)
        gh("run", "download", state["run_id"], "--repo", state["repo"], "--name", "cloud-result", "--dir", str(temp))
        crypt_file(temp / "result.enc", temp / "result.tar.gz", key(), decrypt=True)
        extract_archive(temp / "result.tar.gz", temp / "result")
        project = Path(state["project"])
        # Results are isolated by job; fetching an old render never overwrites a newer one.
        destination = project / "out" / args.job
        if destination.exists():
            raise ValueError(f"Results already exist at {destination}")
        shutil.copytree(temp / "result", destination)
    print(f"Decrypted results: {destination}")


def cleanup(args):
    _, state = job_state(args.job)
    gh("release", "delete", args.job, "--repo", state["repo"], "--yes", "--cleanup-tag")
    if state.get("run_id"):
        gh("run", "delete", state["run_id"], "--repo", state["repo"])
    print("Remote encrypted input and run artifacts removed. Local key and results retained.")


def parser():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("init", help="Install workflow and set repository encryption secret")
    setup.add_argument("--repo", required=True)
    setup.add_argument("--update-workflow", action="store_true")
    send = sub.add_parser("submit", help="Encrypt, upload and dispatch a render")
    send.add_argument("--project", required=True)
    send.add_argument("--mode", choices=["final", "preview", "sheet", "styles", "stills"], default="final")
    send.add_argument("--segment-seconds", type=float, default=60)
    send.add_argument("--workers", type=int, default=2)
    send.add_argument("--from", dest="start", type=float, default=0)
    send.add_argument("--to", dest="end", type=float)
    send.add_argument("--scale", type=float)
    send.add_argument("--times", default="1", help="Comma-separated times for styles/stills")
    send.add_argument("--styles", default="dusk,midnight,golden,neon,storybook")
    for name in ("status", "fetch", "cleanup"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--job", required=True)
        if name == "fetch":
            cmd.add_argument("--wait", action="store_true")
            cmd.add_argument("--diagnostics", action="store_true")
    return ap


if __name__ == "__main__":
    args = parser().parse_args()
    try:
        {"init": init, "submit": submit, "status": status, "fetch": fetch, "cleanup": cleanup}[args.command](args)
    except (Exception, KeyboardInterrupt) as exc:
        print(f"Cloud: {exc}", file=sys.stderr)
        sys.exit(1)
