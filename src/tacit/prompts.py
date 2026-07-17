"""MCP prompts: the team-memory workflow, taught by the server itself.

Clients surface these natively (Claude Code: /mcp__tacit__<name> slash
commands; VS Code: the prompt picker), so teammates get the whole workflow
from the endpoint alone — no AGENTS.md editing, no prompt-crafting, no repo
clone. Defined once here; both runtimes (stdio FastMCP and the Functions
mcp_prompt_trigger) render from this table.

Each prompt returns *instructions to the agent* that drive the memory tools.
"""

from __future__ import annotations

# name -> (description, [(arg_name, arg_description, required), ...])
PROMPT_DEFINITIONS: dict[str, tuple[str, list[tuple[str, str, bool]]]] = {
    "onboard": (
        "Brief me on this project from team memory - run this once when you "
        "start working on an unfamiliar codebase.",
        [],
    ),
    "recall": (
        "Answer a question from team memory before touching the repo.",
        [("question", "What you want to know.", True)],
    ),
    "remember": (
        "Distill a learning into a well-formed team memory and store it.",
        [
            ("learning", "The fact/gotcha/decision to store. Leave empty to use "
             "the most recent learning from this conversation.", False),
        ],
    ),
    "harvest": (
        "End-of-session sweep: find every durable learning from this "
        "conversation that isn't in team memory yet, and store each one.",
        [],
    ),
}


def render(name: str, arguments: dict[str, str] | None = None) -> str:
    args = arguments or {}
    if name == "onboard":
        return (
            "I'm starting work on this project. Brief me from team memory:\n"
            "1. Call memory_brief for the onboarding pack.\n"
            "2. Call memory_list to see what other knowledge exists (gotchas, "
            "architecture, conventions).\n"
            "3. Give me a concise summary: how to set up, the gotchas most "
            "likely to bite me this week, and the conventions my PRs must meet.\n"
            "Do NOT explore the repository for anything team memory already answers."
        )
    if name == "recall":
        question = args.get("question", "").strip() or "(ask me for the question)"
        return (
            f"Answer this from team memory FIRST: {question}\n"
            "Call memory_search with focused keywords (try twice with different "
            "phrasings if the first search misses). Answer from the returned "
            "memories and cite their paths. Only if memory has nothing relevant, "
            "say so explicitly and then fall back to exploring the repository."
        )
    if name == "remember":
        learning = args.get("learning", "").strip()
        subject = (
            f"Store this learning in team memory: {learning}"
            if learning
            else "Review this conversation and store the most recent significant "
            "learning (a non-obvious fix, gotcha, decision, or convention) in team memory."
        )
        return (
            f"{subject}\n"
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
    if name == "harvest":
        return (
            "Sweep this entire conversation for durable learnings the team should "
            "keep: non-obvious fixes, gotchas that cost time, decisions made, "
            "conventions established. For EACH one:\n"
            "1. memory_search to check it isn't already stored.\n"
            "2. If new: memory_create (path /<category>/<slug>.md, '# Title' "
            "heading, 2-6 line body, tags).\n"
            "3. If stale coverage exists: memory_read then memory_update with the "
            "corrected fact.\n"
            "Skip trivia, secrets, and anything derivable by reading the code. "
            "Finish with a one-line-per-memory list of what you stored or updated."
        )
    raise ValueError(f"unknown prompt {name!r}")
