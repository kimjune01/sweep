"""`sweep project-info <repo>` -- emit a repo's canonical project info as JSON.

Used by LLM-spawned subprocesses (inside /investigate, /synth-test, etc.)
to learn the same env routing facts qa will use. Read-only.

  sweep project-info pyro-ppl/pyro
  sweep project-info pyro-ppl/pyro --field test_env

The --field flag drops the JSON envelope so the LLM can substitute it
directly into a downstream command (e.g.
`docker run --rm $(sweep project-info $REPO --field test_env | sed 's/^docker://')`).
"""

from __future__ import annotations

import json

import typer

from sweep import project_info


def register(app: typer.Typer) -> None:
    app.command("project-info")(project_info_cmd)


def project_info_cmd(
    repo: str = typer.Argument(..., help="owner/repo"),
    field: str = typer.Option(
        None, "--field",
        help="Print a single field's value (raw, no JSON envelope).",
    ),
) -> None:
    """Resolve and print a repo's project info: worktree path, test_env, test_cmd, etc."""
    pi = project_info.info(repo)
    if field:
        d = pi.to_dict()
        if field not in d:
            raise typer.BadParameter(
                f"unknown field {field!r}; valid: {sorted(d.keys())}"
            )
        v = d[field]
        print(v if v is not None else "")
        return
    print(json.dumps(pi.to_dict(), indent=2))
