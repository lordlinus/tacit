# Tacit Knowledge Sharing with GitHub Copilot

## Strong scenario: “The incident only one developer knows how to fix”

A critical payment service starts failing on a Friday evening. **Developer A**, who built the retry and reconciliation logic six months ago, is unavailable. **Developer B** is asked to resolve the incident.

GitHub Copilot can explain the code, identify call paths, and suggest fixes—but it cannot know the undocumented history:

- Why a seemingly unnecessary timeout exists
- Which “obvious” fix was previously attempted and caused duplicate payments
- Which downstream system violates its published contract
- Why the team deliberately chose reconciliation over automatic retries
- What dashboards, logs, and test cases Developer A used to diagnose the issue

That is the gap your asset fills.

## The story

### Act 1: Copilot knows the code—but not the story

Developer B opens the repository and asks Copilot:

> “Why don’t we automatically retry failed payment confirmations?”

Copilot examines the current code and proposes adding retries. The suggestion looks technically correct, but it could create duplicate charges.

Use this line in the video:

> **“The code tells Copilot what the system does. It does not always tell it why the team made it that way.”**

### Act 2: Developer A’s experience has become project memory

During Developer A’s earlier GitHub sessions, your MCP server captured durable engineering knowledge from the work:

- The issue being solved
- Hypotheses investigated
- Failed approaches and their outcomes
- Architectural decisions and trade-offs
- Important files, commits, PRs, tests, and operational signals
- Warnings and undocumented system behavior

This memory is connected to the repository and project—not trapped inside Developer A’s chat history or personal recollection.

Developer B asks through the MCP-enabled GitHub environment:

> “Has anyone previously investigated retries for payment confirmations?”

The system retrieves the relevant memory:

> “Developer A tested automatic retries during the reconciliation redesign. The downstream provider sometimes completes a transaction while returning a timeout. Retrying can duplicate the charge. The team therefore records the transaction as uncertain and verifies it through reconciliation. See PR #184, test `duplicate_confirmation`, and the provider incident notes.”

Now Copilot can reason with both **the code** and **the experience behind the code**.

### Act 3: Knowledge travels beyond the IDE

Developer B asks a follow-up:

> “Based on that history, what is the safest mitigation for the current incident?”

Copilot proposes a repository-specific response: preserve the no-retry rule, increase reconciliation frequency, validate against the known duplicate-payment test, and monitor the identified operational signals.

The incident lead can access the same project memory through the Agent Toolkit integration in Teams:

> “Why are we not enabling retries, and what is the recommended mitigation?”

Teams returns a concise, grounded explanation. Engineering, support, and incident management now share the same context without locating Developer A or interrupting another specialist.

## Suggested 3-minute video flow

| Time | Scene | Message |
|---|---|---|
| 0:00–0:20 | Payment incident appears; Developer A is unavailable | Critical knowledge is often attached to a person |
| 0:20–0:45 | Developer B asks Copilot about the code | Copilot understands implementation, but undocumented intent is missing |
| 0:45–1:10 | Copilot suggests the plausible but dangerous retry change | Technically reasonable does not always mean organizationally correct |
| 1:10–1:40 | Developer B queries project memory through your MCP server | Previous investigations, decisions, and warnings become discoverable |
| 1:40–2:10 | Copilot produces a safer, context-aware mitigation | Historical experience improves present-day reasoning |
| 2:10–2:35 | Incident lead asks the same question in Teams | Knowledge is available beyond one developer and one interface |
| 2:35–3:00 | Show incident resolved and memory from B’s session added | Every solved problem strengthens the organization’s future memory |

## The marketing position

Avoid presenting the product as merely **“recording Copilot sessions.”** That sounds like chat archiving. Position it as:

> **A project memory layer that turns developer problem-solving into reusable organizational knowledge.**

The differentiation is clear:

- **Copilot** helps developers understand and produce code.
- **Documentation** captures what someone intentionally wrote down.
- **Your asset** preserves the reasoning, trade-offs, failed attempts, and discoveries generated while real work happens.
- **MCP** makes that memory available to agents in other GitHub environments.
- **Teams and Agent Toolkit** make the same memory accessible across the organization.

## Strong opening narration

> “Every software project has two codebases. One is stored in GitHub. The other lives in the memories of the developers who built it. GitHub Copilot can read the first—but when an incident happens, a developer changes teams, or a decision must be revisited, the second is often the knowledge that matters most.”

## Closing narration

> “Developer A solved the problem once. Developer B should not have to rediscover everything from scratch. By converting development sessions into governed project memory, we allow every developer—and every connected agent—to build on the organization’s accumulated experience.”

## Tagline options

- **Your code is in GitHub. Now your engineering memory can be too.**
- **Copilot understands the code. Project Memory preserves the why.**
- **Turn every developer session into organizational intelligence.**
- **Stop rediscovering what your organization has already learned.**
- **When developers move on, their engineering context should not.**

## Credibility and governance

Describe the asset as capturing **useful, governed, traceable memories**, rather than “all memory.” Buyers will immediately care about permissions, repository boundaries, sensitive-data filtering, retention, provenance, and the ability to link every memory back to evidence.
