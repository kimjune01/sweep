"""Repo↔host compatibility detector — declarative, no LLM.

Given a repo and the local host, returns a verdict + the signals that
drove it. The point is to filter out repos whose tests can't run on
this host *before* sift/triage burns tokens on them. Wrong-architecture
mismatches are static metadata — read from CI workflows + README — not
something to discover at attest time via flaky qemu.

Signals (cheap, ordered):

  1. `.github/workflows/*.yml` runs-on values
     - ALL runs-on are unrunnable here (windows-* / self-hosted-only)
                                            → incompatible. Cross-platform
       matrices with at least one ubuntu/macos entry are NOT flagged —
       we'd just attest against the runnable job.
     - some ubuntu-* / macos-*              → compatible (can run via Docker / native)
  2. README first ~2KB keyword scan
     - architecture-sensitive vocabulary ("x86_64", "amd64", "ELF", "linker",
       "linux-only", etc.) when our host is arm64-darwin → mark as suspect

Verdicts: "ok", "incompatible", "suspect" (operator decides).

Good enough for v1 — caches via gh_io. Extend as we see false positives /
negatives.
"""

from __future__ import annotations

import platform
import re
from dataclasses import dataclass
from typing import Literal

from sweep import gh_io


Verdict = Literal["ok", "incompatible", "suspect"]


@dataclass
class HostCompat:
    verdict: Verdict
    reason: str
    runs_on: list[str]
    readme_hits: list[str]


_RUNS_ON_RE = re.compile(r"^\s*runs-on:\s*(.+?)\s*$", re.MULTILINE)

# Substrings we treat as evidence of host-arch sensitivity. Tuned for
# darwin-arm64 hosts; expand if we onboard other hosts.
_ARCH_KEYWORDS = [
    "x86_64 linker", "x86-64 linker", "amd64 linker",
    "elf linker", "elf binaries",
    "linux-only", "linux only",
    "windows only", "windows-only",
    "macos-only", "macos only",  # ironic on darwin but catches "needs old mac"
]

_BAD_RUNS_ON = re.compile(r"^(windows-|self-hosted)", re.IGNORECASE)


# Hand-curated repos we know can't be attested on darwin-arm64 without
# heroic effort (GPU/CUDA stacks, linux kernel internals, windows-only
# UI/driver code). Reason is shown in the andon / sift drop event so an
# operator can decide whether to override. Keyed lowercase for cheap
# case-insensitive match; the value is the human reason. Extend as
# attest halts surface new "obviously not runnable here" patterns.
#
# Tight by design: a wrong entry drops a viable PR target permanently.
# When in doubt, leave it off — the runtime test_env gate is still
# behind this as a backstop.
_INCOMPATIBLE_REPOS: dict[str, str] = {
    # GPU / compute
    "tracel-ai/cubecl": "CUDA/WGPU compute — no GPU runtime on darwin host",
    "nvidia/cutlass": "CUDA template library — nvcc not on darwin",
    "vllm-project/vllm": "CUDA inference server",
    "dao-ailab/flash-attention": "CUDA kernels",
    "pytorch/tensorrt": "TensorRT (linux/nvidia only)",
    "triton-lang/triton": "GPU kernel compiler (linux/nvidia)",
    "nvidia/apex": "CUDA mixed-precision (linux/nvidia)",
    "rocm/composable_kernel": "ROCm (linux-only)",
    # Kernel / eBPF / linux internals
    "iovisor/bcc": "eBPF tooling (linux kernel)",
    "iovisor/bpftrace": "eBPF tracing (linux kernel)",
    "cilium/cilium": "eBPF networking (linux kernel)",
    "cilium/ebpf": "eBPF go bindings (linux kernel)",
    "aya-rs/aya": "eBPF rust bindings (linux kernel)",
    "libbpf/libbpf": "eBPF C lib (linux kernel)",
    "torvalds/linux": "the linux kernel",
    "systemd/systemd": "linux init system",
    # Linker / loader / linux-only toolchain
    "rui314/mold": "linker — macOS support dropped",
    "firecracker-microvm/firecracker": "KVM-only microvm",
    "cloud-hypervisor/cloud-hypervisor": "KVM-only hypervisor",
    # Linux-stack infra
    "zulip/zulip": "linux-locked server stack",
    "envoyproxy/envoy": "linux-heavy C++ proxy",
    "nginx/unit": "linux app server",
    "haproxy/haproxy": "linux network proxy",
    "openzfs/zfs": "ZFS kernel module",
    "lxc/lxc": "linux containers",
    "containers/crun": "OCI runtime (linux cgroups/namespaces)",
    "opencontainers/runc": "OCI runtime (linux cgroups/namespaces)",
    # Wayland / linux display
    "swaywm/sway": "wayland compositor (linux-only)",
    "smithay/smithay": "wayland toolkit (linux-only)",
    # Windows-only UI / shell
    "microsoft/powertoys": "Win32/WinUI3 shell extensions",
    "files-community/files": "WinUI 3 file manager",
    "microsoft/terminal": "Windows Terminal (Win32 + ConPTY)",
    "valinet/explorerpatcher": "explorer.exe shim",
    # DirectX / D3D
    "microsoft/directx-graphics-samples": "Direct3D samples",
    "microsoft/directxtk": "Direct3D toolkit",
    "microsoft/directxtk12": "Direct3D 12 toolkit",
    "microsoft/directxshadercompiler": "DXC (windows-canonical build)",
    # Windows drivers / kernel-mode
    "microsoft/windows-driver-samples": "WDK driver samples",
    "winsiderss/systeminformer": "windows kernel driver",
    "ramonunch/altsnap": "Win32 hooks",
    # .NET Framework / WinForms / WPF
    "dotnet/winforms": "net*-windows TFM",
    "dotnet/wpf": "WPF (windows desktop)",
    "icsharpcode/sharpdevelop": "net48 IDE",
    "gerardog/gsudo": "Win32 elevation",
    # PowerShell modules
    "powershell/psreadline": "PowerShell line editor",
    "dahlbyk/posh-git": "PowerShell module",
    "powershell/powershellget": "PowerShell package manager",
    "chocolatey/choco": "Windows package manager (MSI/registry)",
    # WSL host-side utilities
    "microsoft/wsl": "WSL kernel/userspace (windows host)",
    "microsoft/wslg": "WSL GUI bridge (windows host)",
    "microsoft/wsl-distrolauncher": "WSL distro launcher",
    # MSI / WiX
    "wixtoolset/wix": "Windows installer toolchain",
    "squirrel/squirrel.windows": "Windows app installer",
    # Win32 metadata / interop
    "microsoft/cswin32": "C#/Win32 source generator",
    "microsoft/windowsappsdk": "Windows App SDK",
    "microsoft/win32metadata": "Win32 metadata projection",
}


# GitHub topics with high precision for "host-incompatible on
# darwin-arm64". A repo with any of these on its topics list is
# treated as incompatible unless explicitly opted-in by the operator.
# Keep tight — false positives drop viable repos. Add only after
# seeing repeated andon halts trace back to a topic we don't catch.
_INCOMPATIBLE_TOPICS: dict[str, str] = {
    # Linux internals
    "ebpf": "eBPF (linux kernel)",
    "bpf": "BPF (linux kernel)",
    "xdp": "XDP (linux kernel)",
    "kernel-module": "linux kernel module",
    "linux-kernel": "linux kernel code",
    "io-uring": "io_uring (linux 5.1+)",
    "landlock": "landlock (linux LSM)",
    "seccomp": "seccomp (linux syscall filter)",
    "systemd": "systemd (linux init)",
    "wayland": "wayland display server (linux)",
    "drm": "Direct Rendering Manager (linux GPU)",
    "kvm": "KVM (linux hypervisor)",
    "dpdk": "DPDK (linux user-space networking)",
    "nftables": "nftables (linux netfilter)",
    "iptables": "iptables (linux netfilter)",
    # GPU / compute
    "cuda": "CUDA (nvidia GPU, linux/windows)",
    "rocm": "ROCm (AMD GPU, linux-only)",
    "nvidia": "nvidia GPU stack",
    "tensorrt": "TensorRT (nvidia inference)",
    "gpgpu": "GPGPU compute",
    # Windows internals / UI
    "windows-driver": "Windows kernel driver",
    "windows-kernel": "Windows kernel code",
    "wdk": "Windows Driver Kit",
    "directx": "DirectX (windows)",
    "direct3d": "Direct3D (windows)",
    "direct3d11": "Direct3D 11",
    "direct3d12": "Direct3D 12",
    "winapi": "Win32 API",
    "win32api": "Win32 API",
    "mfc": "MFC (windows)",
    "atl": "ATL (windows)",
    "powershell-module": "PowerShell module",
    "dotnet-framework": ".NET Framework (windows-only)",
    "net-framework": ".NET Framework (windows-only)",
    "wpf": "WPF (windows desktop)",
    "winforms": "WinForms (windows desktop)",
    "uwp": "UWP (windows-only)",
    "winui": "WinUI (windows-only)",
    "winui3": "WinUI 3 (windows-only)",
    "wix": "WiX installer (windows)",
    "wix-toolset": "WiX toolset (windows)",
    "msi": "MSI installer (windows)",
    "msix": "MSIX packaging (windows)",
    "wsl": "WSL (windows host)",
    "wsl2": "WSL2 (windows host)",
}


# Substrings that scream "this repo targets a host we can't satisfy"
# from just the repo name / description / topics. Used by cheap_check
# which makes zero API calls — pure string pattern. Conservative on
# purpose: false positives drop viable candidates, so the list stays
# tight. Extend as we see scout leaking obvious cases into sift.
_CHEAP_INCOMPAT_PATTERNS = [
    "powershell",
    "windows-",
    ".net-framework",
    "wslg", "wsl-utilities",
    "msys2",
]


def cheap_check(repo: str, *, description: str = "",
                 topics: list[str] | None = None) -> HostCompat:
    """Zero-API string match for the most obvious incompat repos.
    Used at scout-time before any per-repo API call. Anything that
    needs structured signal (workflows / readme) belongs in `check()`
    and runs at sift-time.
    """
    # Hand-curated denylist — same dict `check()` uses, just lifted
    # earlier so scout drops these before spending any API budget.
    repo_lc = repo.lower()
    if repo_lc in _INCOMPATIBLE_REPOS:
        return HostCompat(
            verdict="incompatible",
            reason=f"denylisted: {_INCOMPATIBLE_REPOS[repo_lc]}",
            runs_on=[], readme_hits=[],
        )
    # Topic-based check is free here too if scout already had topics
    # in hand (gh search payloads include them). Avoids a sift-time
    # API call when the signal is already present.
    for t in (topics or []):
        tl = t.lower()
        if tl in _INCOMPATIBLE_TOPICS:
            return HostCompat(
                verdict="incompatible",
                reason=f"topic {tl!r}: {_INCOMPATIBLE_TOPICS[tl]}",
                runs_on=[], readme_hits=[t for t in (topics or []) if t.lower() in _INCOMPATIBLE_TOPICS],
            )
    needle = " ".join([
        repo.lower(),
        (description or "").lower(),
        " ".join((topics or [])).lower(),
    ])
    for pat in _CHEAP_INCOMPAT_PATTERNS:
        if pat in needle:
            return HostCompat(
                verdict="incompatible",
                reason=f"name/description matches {pat!r} — host-incompatible",
                runs_on=[], readme_hits=[],
            )
    return HostCompat(verdict="ok", reason="cheap check passed",
                      runs_on=[], readme_hits=[])


def _host_arch_native() -> str:
    """One of: 'arm64', 'amd64', 'unknown'. Used to interpret keyword hits."""
    m = platform.machine().lower()
    if m in ("arm64", "aarch64"):
        return "arm64"
    if m in ("x86_64", "amd64"):
        return "amd64"
    return "unknown"


def _list_workflows(repo: str) -> list[str]:
    """File names under .github/workflows. Empty list = no CI declared."""
    try:
        entries = gh_io.api(f"/repos/{repo}/contents/.github/workflows", ttl=3600)
    except Exception:
        return []
    if not isinstance(entries, list):
        return []
    return [e["name"] for e in entries
            if isinstance(e, dict) and e.get("name", "").endswith((".yml", ".yaml"))]


def _workflow_text(repo: str, name: str) -> str:
    try:
        entry = gh_io.api(
            f"/repos/{repo}/contents/.github/workflows/{name}", ttl=3600,
        )
    except Exception:
        return ""
    if not isinstance(entry, dict):
        return ""
    content = entry.get("content", "") or ""
    encoding = entry.get("encoding", "")
    if encoding == "base64":
        import base64
        try:
            return base64.b64decode(content).decode("utf-8", errors="replace")
        except Exception:
            return ""
    return content


def _readme_text(repo: str) -> str:
    try:
        entry = gh_io.api(f"/repos/{repo}/readme", ttl=24 * 3600)
    except Exception:
        return ""
    if not isinstance(entry, dict):
        return ""
    content = entry.get("content", "") or ""
    encoding = entry.get("encoding", "")
    if encoding == "base64":
        import base64
        try:
            return base64.b64decode(content).decode("utf-8", errors="replace")[:2048]
        except Exception:
            return ""
    return content[:2048]


def _repo_topics(repo: str) -> list[str]:
    """GitHub topics for the repo. Empty list on any failure — the rest
    of `check()` still does useful work without them."""
    try:
        data = gh_io.api(f"/repos/{repo}/topics", ttl=24 * 3600)
    except Exception:
        return []
    if isinstance(data, dict):
        names = data.get("names")
        if isinstance(names, list):
            return [n for n in names if isinstance(n, str)]
    return []


def check(repo: str) -> HostCompat:
    """Compute the host-compat verdict for one repo. Cached transitively
    through gh_io's TTL."""
    # Hand-curated denylist first — zero-cost dict lookup. These are
    # repos we've decided up-front are not worth attempting on this
    # host; runtime test_env gate would refuse them anyway, this just
    # short-circuits the work.
    repo_lc = repo.lower()
    if repo_lc in _INCOMPATIBLE_REPOS:
        return HostCompat(
            verdict="incompatible",
            reason=f"denylisted: {_INCOMPATIBLE_REPOS[repo_lc]}",
            runs_on=[], readme_hits=[],
        )

    # Topic-based check next — one cheap API call (24h TTL). Catches
    # repos that match a known-bad ecosystem (cuda, ebpf, wpf, …) even
    # if we haven't added them to the explicit denylist.
    topics = _repo_topics(repo)
    for t in topics:
        tl = t.lower()
        if tl in _INCOMPATIBLE_TOPICS:
            return HostCompat(
                verdict="incompatible",
                reason=f"topic {tl!r}: {_INCOMPATIBLE_TOPICS[tl]}",
                runs_on=[], readme_hits=[t for t in topics if t.lower() in _INCOMPATIBLE_TOPICS],
            )

    host_arch = _host_arch_native()
    runs_on_values: list[str] = []
    bad_runs_on: list[str] = []
    for wf in _list_workflows(repo)[:20]:  # cap to avoid huge repos
        text = _workflow_text(repo, wf)
        for m in _RUNS_ON_RE.finditer(text):
            val = m.group(1).strip()
            runs_on_values.append(val)
            if _BAD_RUNS_ON.match(val):
                bad_runs_on.append(val)

    # Incompatible only when EVERY concrete runs-on is unrunnable. A
    # matrix that includes ubuntu / macos plus a windows job is fine —
    # we'd just attest against an ubuntu (Docker) or macos (native)
    # build. Matrix-expression entries (`${{ matrix.os }}`) are
    # ambiguous; treat as runnable to avoid false negatives.
    def _runnable(val: str) -> bool:
        if val.startswith("${{"):
            return True  # unknown → assume runnable, don't drop on uncertainty
        return not _BAD_RUNS_ON.match(val)

    concrete = [v for v in runs_on_values if not v.startswith("${{")]
    if concrete and not any(_runnable(v) for v in concrete):
        return HostCompat(
            verdict="incompatible",
            reason=f"every runs-on entry ({sorted(set(concrete))}) is "
                   f"unrunnable on this host",
            runs_on=sorted(set(runs_on_values)),
            readme_hits=[],
        )

    readme = _readme_text(repo).lower()
    readme_hits = [kw for kw in _ARCH_KEYWORDS if kw in readme]
    # On arm64, arch-locked keywords flip the verdict to "suspect".
    # On amd64 hosts we'd ignore most of these (still likely runnable
    # natively or via cross-arch tooling).
    if readme_hits and host_arch == "arm64":
        return HostCompat(
            verdict="suspect",
            reason=f"README mentions {readme_hits[0]!r}; host is arm64 — "
                   f"tests may require x86_64",
            runs_on=sorted(set(runs_on_values)),
            readme_hits=readme_hits,
        )

    return HostCompat(
        verdict="ok",
        reason="no host-arch incompatibility detected",
        runs_on=sorted(set(runs_on_values)),
        readme_hits=readme_hits,
    )
