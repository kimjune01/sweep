"""`sweep wish` — file an explicit wish for a CLI shape that should exist.

Companion to the implicit missing-calls log. When an agent reaches for a
CLI command that doesn't exist, the harness logs the reach automatically
(see sweep.cli.__init__.main). That's an implicit vote. `sweep wish` is
the explicit channel: the agent (or a human) deliberately files a
request with a stated reason.

Both implicit reaches and explicit wishes feed the same wishlist; wishes
weight 3× because the reason carries higher signal than a syntactic
guess. See https://june.kim/jit-cli for the framing.
"""

from __future__ import annotations

import json
import shlex

import typer

from sweep import missing_calls


def register(app: typer.Typer) -> None:
    app.command("wish")(wish_cmd)


def wish_cmd(
    command: str = typer.Argument(
        ...,
        help="The wished-for command shape, e.g. 'sweep drip cooldown-stats --repo X'",
    ),
    reason: str = typer.Option(
        ...,
        "--reason",
        "-r",
        help="One-line justification — what this would enable that's currently hard",
    ),
) -> None:
    """File an explicit wish for a CLI shape that should exist.

    The wish goes into the same wishlist `sweep missing` reads, marked
    `kind: "wish"` and weighted 3× over implicit reaches. The reason is
    the signal that wasn't available from the failed-reach channel.
    """
    # Split the command into argv. Strip a leading `sweep` if present so
    # the wishlist stores the same shape as implicit reaches.
    try:
        argv = shlex.split(command)
    except ValueError as e:
        raise typer.BadParameter(f"could not parse command: {e}")
    if argv and argv[0] == "sweep":
        argv = argv[1:]
    if not argv:
        raise typer.BadParameter("empty command — what are you wishing for?")
    entry = missing_calls.wish(argv, reason)
    print(json.dumps(entry, separators=(",", ":")))
