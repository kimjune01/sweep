"""`sweep cache` — manage the build cache and the sweep-tester image.

The build cache is per-repo at ~/.sweep/build-cache/<owner__repo>/
mounted into the docker test container at /cache. The sweep-tester
image is the fat default test_env (Rust + Go + Python + Node + C++
toolchain) — built once, reused across every repo whose retro_params
doesn't pin a specific test_env.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import typer


cache_app = typer.Typer(
    help="Manage build cache and the sweep-tester docker image.",
    no_args_is_help=True,
)

BUILD_CACHE_ROOT = Path.home() / ".sweep" / "build-cache"
SWEEP_TESTER_TAG = "sweep-tester:latest"
DOCKERFILE_DIR = Path(__file__).resolve().parent.parent / "dockerfiles" / "sweep-tester"


def _du_bytes(path: Path) -> int:
    try:
        r = subprocess.run(
            ["du", "-sk", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return 0
        return int(r.stdout.split()[0]) * 1024
    except (subprocess.TimeoutExpired, ValueError, IndexError):
        return 0


@cache_app.command("show")
def cache_show() -> None:
    """List per-repo cache sizes and totals."""
    if not BUILD_CACHE_ROOT.exists():
        print(f"(no cache root at {BUILD_CACHE_ROOT})")
        return
    rows = []
    total = 0
    for d in sorted(BUILD_CACHE_ROOT.iterdir()):
        if not d.is_dir():
            continue
        size = _du_bytes(d)
        total += size
        rows.append((d.name, size, d.stat().st_mtime))
    rows.sort(key=lambda r: -r[1])
    for name, size, mtime in rows:
        gb = size / 1024**3
        import datetime as dt
        age_d = (dt.datetime.now().timestamp() - mtime) / 86400
        print(f"  {gb:6.2f} GB  {age_d:5.1f}d old  {name}")
    print(f"  ────────")
    print(f"  {total / 1024**3:6.2f} GB  total across {len(rows)} repos")


@cache_app.command("prune")
def cache_prune(
    repo: str = typer.Option(None, help="Prune one repo's cache (owner/repo)."),
    all_: bool = typer.Option(False, "--all", help="Wipe the entire build cache."),
) -> None:
    """Manually drop cache entries. Without args, runs the auto LRU
    prune to enforce the size cap. With --repo, drops one repo. With
    --all, nukes everything (next attest cold-rebuilds)."""
    if all_:
        if not BUILD_CACHE_ROOT.exists():
            print(f"(no cache root at {BUILD_CACHE_ROOT})")
            return
        size = _du_bytes(BUILD_CACHE_ROOT)
        shutil.rmtree(BUILD_CACHE_ROOT)
        print(f"wiped {size / 1024**3:.2f} GB at {BUILD_CACHE_ROOT}")
        return
    if repo:
        slug = repo.replace("/", "__")
        target = BUILD_CACHE_ROOT / slug
        if not target.exists():
            print(f"(no cache for {repo} at {target})")
            return
        size = _du_bytes(target)
        shutil.rmtree(target)
        print(f"wiped {size / 1024**3:.2f} GB for {repo}")
        return
    # No args — run the auto LRU prune.
    from sweep.activities.qa import _prune_build_cache_if_full
    result = _prune_build_cache_if_full()
    if result["action"] == "none":
        print(f"under cap: {result.get('size_gb', '?')} GB / {result.get('cap_gb', '?')} GB")
    else:
        for d in result["deleted"]:
            print(f"  wiped {d['size_gb']:.2f} GB  {d['path']}")
        print(f"final: {result['final_size_gb']:.2f} GB / {result['cap_gb']} GB")


@cache_app.command("rebuild-image")
def cache_rebuild_image(
    no_cache: bool = typer.Option(False, "--no-cache", help="Pass --no-cache to docker build."),
) -> None:
    """Build the sweep-tester docker image. Run after editing the
    Dockerfile, after a toolchain bump, or to refresh stale layers."""
    if not (DOCKERFILE_DIR / "Dockerfile").exists():
        print(f"!! Dockerfile not found at {DOCKERFILE_DIR}")
        raise typer.Exit(1)
    args = ["docker", "build", "-t", SWEEP_TESTER_TAG]
    if no_cache:
        args.append("--no-cache")
    args.append(str(DOCKERFILE_DIR))
    print(f"$ {' '.join(args)}", flush=True)
    r = subprocess.run(args)
    if r.returncode != 0:
        # Loud failure — earlier we shipped a success line on a failed
        # build because the post-print ran on the same stdout that had
        # already buffered docker's error tail. Print the failure with
        # `flush=True` before raising so the operator sees it.
        print(f"!! docker build failed (rc={r.returncode}); image NOT updated",
              flush=True)
        raise typer.Exit(r.returncode)
    # Sanity check: the build can succeed structurally but produce an
    # image that `docker image inspect` doesn't see (rare; happens with
    # certain buildkit edge cases). Confirm before declaring victory.
    chk = subprocess.run(
        ["docker", "image", "inspect", SWEEP_TESTER_TAG],
        capture_output=True, text=True,
    )
    if chk.returncode != 0:
        print(f"!! docker build returned 0 but {SWEEP_TESTER_TAG} not "
              f"present after build — investigate", flush=True)
        raise typer.Exit(1)
    print(f"built {SWEEP_TESTER_TAG}", flush=True)


@cache_app.command("image-exists")
def cache_image_exists() -> None:
    """Print whether the sweep-tester image is built locally."""
    r = subprocess.run(
        ["docker", "image", "inspect", SWEEP_TESTER_TAG],
        capture_output=True, text=True,
    )
    if r.returncode == 0:
        print(f"present: {SWEEP_TESTER_TAG}")
    else:
        print(f"missing: {SWEEP_TESTER_TAG} — run `sweep cache rebuild-image`")
        raise typer.Exit(1)
