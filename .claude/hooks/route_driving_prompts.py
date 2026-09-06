#!/usr/bin/env python3
"""UserPromptSubmit: make the routing to /drive-run mechanical.

A lightweight model reads "process this dive" and starts typing a command
line. The owner's rule is that a driving request goes through the charter,
preflight and plan first (docs/AGENT_OPERATIONS.md sec.0); this hook
recognises the request and adds one short instruction to the context, so
the routing does not depend on the model remembering it.

It only ADDS context (exit 0, stdout). It never blocks a prompt and it says
nothing on prompts that do not read as a request to run the pipeline, so
ordinary turns pay nothing. Prompts that already start with a slash are
skills and are left alone.

Contract: UserPromptSubmit hook. Payload as JSON on stdin; the text is under
"prompt" (documented) or "user_input" (seen in some builds) - both are read.
ASCII only; stdlib only.
"""
from __future__ import annotations

import json
import re
import sys

#: Verbs that mean "make the pipeline do work", followed within the same
#: sentence by a thing it works on. Questions about the pipeline do not
#: match: "is the run done?" has no imperative verb.
_VERB = (r"\b(run|process|align|merge|model|export|publish|drive|kick\s+off|"
         r"start|launch|re-?run|resume|batch|georeference|extract|reprocess)\b")
_OBJECT = (r"\b(dive|dives|dataset|data\s+set|zone|zones|workspace|campaign|"
           r"component|components|pipeline|imagery|images|expedition|"
           r"overnight|unattended|results?\s+root|the\s+run|H\d{4}|NA\d{3}|"
           r"ON\d{4})\b")
_PHRASES = (r"run (this|it|the pipeline|the chain) against",
            r"process (this|the|that) (dive|dataset|imagery)",
            r"(overnight|unattended) run",
            r"drive (it|this|the run|the pipeline)")

_IMPERATIVE = re.compile(_VERB + r"[^.?!\n]{0,80}" + _OBJECT, re.IGNORECASE)
_PHRASE = re.compile("|".join(_PHRASES), re.IGNORECASE)

MESSAGE = (
    "ROUTING (hook .claude/hooks/route_driving_prompts.py): this reads as a "
    "request to DRIVE the pipeline. Protocol, in order, before any write: "
    "(1) /charter - six answers from the owner, then `python rs.py preflight "
    "--charter <C>` until READY, then owner sign-off; (2) /drive-run - "
    "`python rs.py plan --charter <C> --validate`, then `rs.py run` for "
    "prep stages or `rs.py launch` for RealityScan stages. Never hand-write a "
    "command line; never fill a charter answer from a directory listing. If "
    "the owner only wants a status, use /status instead."
)


def looks_like_driving(text: str) -> bool:
    text = text.strip()
    if not text or text.startswith("/"):
        return False
    return bool(_PHRASE.search(text) or _IMPERATIVE.search(text))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0
    text = payload.get("prompt") or payload.get("user_input") or ""
    if isinstance(text, str) and looks_like_driving(text):
        print(MESSAGE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
