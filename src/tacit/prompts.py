"""MCP prompts: the team-memory workflow, taught by the server itself.

Clients surface these natively (Claude Code: /mcp__tacit__tacit_onboard etc.;
VS Code: the prompt picker), so teammates get the whole workflow from the
endpoint alone — no AGENTS.md editing, no prompt-crafting, no repo clone.
Names carry the tacit_ prefix so it's unmistakable in any client's picker
what the user is invoking. Defined once here; both runtimes render from this
table.

One shared endpoint serves every team project, so each prompt starts by
telling the agent how to pick the right store: infer the project slug from
the repository folder name and pass it on every tool call. Only the agent
knows its working directory — the remote server never does.
"""

from __future__ import annotations

_PROJECT_RULE = (
    "First, determine the project slug: the repository folder name in "
    "kebab-case (e.g. ~/work/Contoso Payments -> contoso-payments; use "
    "`git rev-parse --show-toplevel` if unsure). State which slug you're "
    "using, and pass it as the `project` argument on EVERY memory tool call."
)

# name -> (description, [(arg_name, arg_description, required), ...])
PROMPT_DEFINITIONS: dict[str, tuple[str, list[tuple[str, str, bool]]]] = {
    "tacit_onboard": (
        "Brief me on this project from team memory - run this once when you "
        "start working on an unfamiliar codebase.",
        [],
    ),
    "tacit_recall": (
        "Answer a question from team memory before touching the repo.",
        [("question", "What you want to know.", True)],
    ),
    "tacit_remember": (
        "Distill a learning into a well-formed team memory and store it.",
        [
            ("learning", "The fact/gotcha/decision to store. Leave empty to use "
             "the most recent learning from this conversation.", False),
        ],
    ),
    "tacit_harvest": (
        "End-of-session sweep: find every durable learning from this "
        "conversation that isn't in team memory yet, and store each one.",
        [],
    ),
}


def render(name: str, arguments: dict[str, str] | None = None) -> str:
    args = arguments or {}
    if name == "tacit_onboard":
        return (
            f"I'm starting work on this project. {_PROJECT_RULE}\n"
            "Then brief me from team memory:\n"
            "1. Call memory_brief for the onboarding pack.\n"
            "2. Call memory_list to see what other knowledge exists (gotchas, "
            "architecture, conventions).\n"
            "3. Give me a concise summary: how to set up, the gotchas most "
            "likely to bite me this week, and the conventions my PRs must meet.\n"
            "If both come back empty, say this project has no team memory yet "
            "and offer to start it with tacit_remember as you work. Do NOT "
            "explore the repository for anything team memory already answers."
        )
    if name == "tacit_recall":
        question = args.get("question", "").strip() or "(ask me for the question)"
        return (
            f"Answer this from team memory FIRST: {question}\n"
            f"{_PROJECT_RULE}\n"
            "Call memory_search with focused keywords (try twice with different "
            "phrasings if the first search misses). Answer from the returned "
            "memories and cite their paths. Only if memory has nothing relevant, "
            "say so explicitly and then fall back to exploring the repository."
        )
    if name == "tacit_remember":
        learning = args.get("learning", "").strip()
        subject = (
            f"Store this learning in team memory: {learning}"
            if learning
            else "Review this conversation and store the most recent significant "
            "learning (a non-obvious fix, gotcha, decision, or convention) in team memory."
        )
        return (
            f"{subject}\n"
            f"{_PROJECT_RULE}\n"
            "Write it as ONE focused memory:\n"
            "- path: /<category>/<short-slug>.md (categories: onboarding | gotcha | "
            "architecture | convention | general)\n"
            "- content: a '# Title' line that states the fact (search ranks titles "
            "heavily), then 2-6 lines: symptom, root cause, the fix/rule, and any "
            "command or setting verbatim.\n"
            "- tags: 2-4 comma-separated keywords.\n"
            "First memory_search to check it isn't already stored - if a memory "
            "covers it, memory_read then memory_update it instead of creating a "
            "duplicate. Never store secrets or transient debugging state."
        )
    if name == "tacit_harvest":
        return (
            "Sweep this entire conversation for durable learnings the team should "
            f"keep. {_PROJECT_RULE}\n"
            "For EACH learning (non-obvious fixes, gotchas that cost time, "
            "decisions made, conventions established):\n"
            "1. memory_search to check it isn't already stored.\n"
            "2. If new: memory_create (path /<category>/<slug>.md, '# Title' "
            "heading, 2-6 line body, tags).\n"
            "3. If stale coverage exists: memory_read then memory_update with the "
            "corrected fact.\n"
            "Skip trivia, secrets, and anything derivable by reading the code. "
            "Finish with a one-line-per-memory list of what you stored or updated."
        )
    raise ValueError(f"unknown prompt {name!r}")
