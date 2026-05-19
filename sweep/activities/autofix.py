"""Autofix activities — install missing toolchain deps into sweep-tester.

Two `@activity.defn`s, no actor. Any workflow whose activity raises a
"missing tool" failure can invoke these from its except handler to
self-heal the image before re-raising or completing.

  autofix_install(tool)         — install one named tool by allowlist.
  autofix_from_text(text)       — regex-scan failure text, install every
                                  allowlisted tool detected.

Both return a dict with `handled` + per-tool action records. Both edit
the Dockerfile (idempotent) and dispatch `sweep cache rebuild-image`
in a detached subprocess; callers don't block on the rebuild.

The CLI surface (`sweep autofix install <tool>` / `sweep autofix run
<text>`) calls the underlying plain functions, not the temporal
activities — the activities exist for workflow callers.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from temporalio import activity

from sweep import observe


DOCKERFILE = Path(__file__).resolve().parent.parent / "dockerfiles" / "sweep-tester" / "Dockerfile"


# Map tool name → (install_method, package_or_arg). Install methods:
#   "apt"     — append to apt-get install -y block
#   "uv-tool" — append to uv tool install layer
#   "cargo"   — append a new RUN cargo install line in the Rust layer
ALLOWLIST: dict[str, tuple[str, str]] = {
    # Python tooling
    "ruff":    ("uv-tool", "ruff"),
    "black":   ("uv-tool", "black"),
    "mypy":    ("uv-tool", "mypy"),
    "pytest":  ("uv-tool", "pytest"),
    "tox":     ("uv-tool", "tox"),
    "hatch":   ("uv-tool", "hatch"),
    "poetry":  ("uv-tool", "poetry"),
    "bandit":  ("uv-tool", "bandit"),
    "isort":   ("uv-tool", "isort"),
    "pylint":  ("uv-tool", "pylint"),

    # System tools
    "mold":    ("apt", "mold"),
    "lld":     ("apt", "lld"),
    "jq":      ("apt", "jq"),
    "yq":      ("apt", "yq"),
    "protoc":  ("apt", "protobuf-compiler"),

    # Rust tooling
    "sccache":       ("cargo", "sccache"),
    "cargo-make":    ("cargo", "cargo-make"),
    "cargo-nextest": ("cargo", "cargo-nextest"),
}


DETECT_PATTERNS = [
    re.compile(r"\b([\w][\w.-]*?): command not found"),
    re.compile(r"No such file or directory:\s*['\"]([\w][\w.-]*?)['\"]"),
    re.compile(r"\bmake:\s*([\w][\w.-]*?):\s*No such file or directory"),
    re.compile(r"-fuse-ld=([\w][\w-]*)"),
    re.compile(r"Could not find\s+[`'\"]([\w][\w.-]*?)[`'\"]"),
    re.compile(r"\b([\w][\w.-]*?): not found"),
]
_SKIP_WORDS = {"the", "no", "or", "a", "an", "it", "is", "be"}


def detect_missing_tools(text: str) -> list[str]:
    """Scan `text` for missing-tool patterns. Returns deduped tool names."""
    seen: list[str] = []
    for pat in DETECT_PATTERNS:
        for m in pat.finditer(text):
            tool = m.group(1).strip()
            if not tool or tool in _SKIP_WORDS or tool in seen:
                continue
            if len(tool) < 2 or tool.isdigit():
                continue
            seen.append(tool)
    return seen


def _already_in_dockerfile(pkg: str) -> bool:
    if not DOCKERFILE.exists():
        return False
    return pkg in DOCKERFILE.read_text()


def _append_apt(pkg: str) -> bool:
    text = DOCKERFILE.read_text()
    m = re.search(
        r"(RUN apt-get update && apt-get install -y --no-install-recommends\s*\\\n)"
        r"((?:\s+\S+\s*\\\n)+)"
        r"(\s+&& rm -rf /var/lib/apt/lists/\*)",
        text, re.MULTILINE,
    )
    if not m:
        return False
    header, body, footer = m.group(1), m.group(2), m.group(3)
    lines = [l for l in body.splitlines() if l.strip()]
    new_line = f"        {pkg} \\"
    inserted = False
    out_lines: list[str] = []
    for line in lines:
        existing = line.strip().rstrip("\\").strip()
        if not inserted and pkg < existing:
            out_lines.append(new_line)
            inserted = True
        out_lines.append(line)
    if not inserted:
        out_lines.append(new_line)
    new_body = "\n".join(out_lines) + "\n"
    DOCKERFILE.write_text(text[:m.start()] + header + new_body + footer + text[m.end():])
    return True


def _append_uv_tool(name: str) -> bool:
    text = DOCKERFILE.read_text()
    m = re.search(
        r"(RUN uv tool install [a-zA-Z0-9_-]+(?:\s*\\\n\s+&& uv tool install [a-zA-Z0-9_-]+)*)",
        text,
    )
    if not m:
        return False
    block = m.group(1)
    if f"uv tool install {name}" in block:
        return True
    new_block = block.rstrip() + f" \\\n    && uv tool install {name}"
    DOCKERFILE.write_text(text.replace(block, new_block))
    return True


def _append_cargo(spec: str) -> bool:
    text = DOCKERFILE.read_text()
    if f"cargo install {spec}" in text:
        return True
    m = re.search(r"(RUN cargo install [^\n]+(?:\s*\\\n[^\n]+)*\n)", text)
    if not m:
        return False
    insertion = m.group(1) + f"RUN cargo install {spec} --locked\n"
    DOCKERFILE.write_text(text[:m.start()] + insertion + text[m.end():])
    return True


def _kick_rebuild() -> str:
    try:
        subprocess.Popen(
            ["uv", "run", "sweep", "cache", "rebuild-image"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
        return "dispatched"
    except OSError as e:
        return f"failed: {e}"


def _install(tool: str) -> dict:
    """Edit Dockerfile to install `tool`. Returns a dict describing the
    action. Does NOT dispatch the rebuild — callers batch that decision."""
    if tool not in ALLOWLIST:
        return {"handled": False, "tool": tool, "reason": "not in allowlist"}
    method, pkg = ALLOWLIST[tool]
    if _already_in_dockerfile(pkg):
        return {"handled": True, "tool": tool, "method": method,
                "pkg": pkg, "action": "already"}
    ok = {"apt": _append_apt, "uv-tool": _append_uv_tool,
          "cargo": _append_cargo}[method](pkg)
    if not ok:
        return {"handled": False, "tool": tool, "method": method,
                "reason": "dockerfile edit failed (pattern miss)"}
    return {"handled": True, "tool": tool, "method": method, "pkg": pkg,
            "action": "edited"}


@activity.defn
async def autofix_install(tool: str) -> dict:
    """Install one named tool into the image. Workflow-callable.
    Returns {handled, tool, method, pkg, action, rebuild?}."""
    result = _install(tool)
    if result.get("action") == "edited":
        result["rebuild"] = _kick_rebuild()
    observe.event("autofix_install", **result)
    return result


@activity.defn
async def autofix_from_text(text: str) -> dict:
    """Pattern-match `text` for missing-tool failures, install every
    allowlisted tool detected, dispatch ONE rebuild if anything was
    edited. Workflow-callable.

    Returns {handled, results, rebuild, any_unhandled}."""
    tools = detect_missing_tools(text)
    if not tools:
        observe.event("autofix_no_match", text_excerpt=text[:200])
        return {"handled": False, "results": [], "reason": "no pattern match"}
    results = [_install(t) for t in tools]
    any_edited = any(r.get("action") == "edited" for r in results)
    any_unhandled = any(not r.get("handled") for r in results)
    rebuild = _kick_rebuild() if any_edited else "skipped"
    observe.event("autofix_from_text",
                  tools_detected=tools, results=results,
                  rebuild=rebuild, any_unhandled=any_unhandled)
    return {"handled": not any_unhandled, "results": results,
            "rebuild": rebuild, "any_unhandled": any_unhandled}
