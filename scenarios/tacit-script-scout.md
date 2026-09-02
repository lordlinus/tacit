## What changed

Dropped the vendor/idempotency detail entirely. New trap: **"just add retries."** It's the most universal answer in software, it's what Copilot will genuinely say, and the counterintuitive truth — *retries don't rescue a struggling service, they finish it off* — lands in one sentence with zero domain knowledge required.

**Cast:** 2 players — **PRIYA** (Dev A, senior, `orders-api`) and **MARCO** (Dev B, different team, different repo). No narrator; they speak to camera and text cards carry the thesis.

---

# THE ORG THAT FORGOT
### Runtime 4:00 · Two-hander · Screen recording + piece-to-camera

---

## SCENE 1 — COLD OPEN
**0:00 – 0:20**

**VISUAL:** Tight on MARCO, to camera. Behind him, a monitor with a clean, well-formatted block of code visible but out of focus.

> **MARCO:** This is the code Copilot wrote for me.
>
> *(small shrug, genuine)*
>
> Honestly? It's good code. It's exactly what I would have written myself.
>
> *(beat — two full seconds)*
>
> It took our checkout down for forty minutes.

**VISUAL:** Hard cut to black.

---

## SCENE 2 — ACT ONE: SOMEONE ALREADY PAID FOR THIS
**0:20 – 1:05**

**CARD:** `SIX WEEKS EARLIER`

**VISUAL:** PRIYA to camera, then cut to screen recording of her Copilot session — time-lapsed, three rapid-fire failed attempts.

> **PRIYA:** Six weeks earlier, I had the same problem. Our pricing service got slow. So I did the obvious things.

**VISUAL:** Three fast cuts — each a code change, each followed by a worsening latency graph.

> **PRIYA (V.O.):** Raised the timeout. Made it worse.
>
> Added more instances. Made it worse.
>
> Added retries with exponential backoff — and *that's* the one that actually took production down. Every retry tripled the load on a service that was already drowning.

**VISUAL:** Back to PRIYA, to camera.

> **PRIYA:** Three days to learn that retries don't rescue a slow system. They finish it off.
>
> The real fix was the opposite. Fail fast. Open a circuit breaker. Serve a degraded response and stop making it worse.

---

## SCENE 3 — THE GAP
**1:05 – 1:30**

**VISUAL:** Screen recording — her merged PR. Slow zoom onto the commit message: `fix: circuit-break calls to pricing-service`. Green checkmarks. Approved.

> **PRIYA (V.O.):** And here's everything my company kept from those three days.
>
> Nine words and a diff.

**VISUAL:** Cut to PRIYA, to camera.

> **PRIYA:** The three things I tried that *failed*? They're not in the repo. They never are.
>
> You don't commit a dead end.

**CARD (full screen, held 2s):**
> **DEAD ENDS LEAVE NO CODE BEHIND.**

---

## SCENE 4 — ACT TWO: IT HAPPENS AGAIN
**1:30 – 2:10**

**CARD:** `SIX WEEKS LATER · DIFFERENT TEAM · DIFFERENT REPO`

**VISUAL:** MARCO at his desk. Screen recording: he types a prompt into Copilot Chat.

**ON SCREEN:** *"The pricing-service call is timing out. How should I handle this?"*

> **MARCO (V.O.):** I'd never met Priya. Different repo, different continent. Same slow service underneath.

**VISUAL:** Copilot streams out a confident, beautifully formatted answer: *exponential backoff, 3 retries, jitter.* Let it fully render. It should look **excellent.**

> **MARCO (V.O.):** Textbook answer.

**VISUAL:** Cut to MARCO, to camera.

> **MARCO:** It would pass any code review. Because my reviewer didn't know either.

**VISUAL:** Cut to a pager alert / incident channel lighting up. Red. Two seconds of it.

> **MARCO:** Copilot didn't fail me. It gave me the best answer in the world.
>
> It just didn't know the one thing my company already knew.

---

## SCENE 5 — THESIS
**2:10 – 2:25**

**VISUAL:** Black. Cards only. Music swells.

**CARD:** `Copilot gave every developer a memory.`

*(beat)*

**CARD:** `Nobody gave the organization one.`

*(beat)*

**CARD:** `[ASSET NAME]`

---

## SCENE 6 — CAPTURE
**2:25 – 3:00**

**VISUAL:** PRIYA to camera, then her screen — the MCP server connected to her Copilot harness.

> **PRIYA:** So we fixed the actual problem. My Copilot session now runs with a memory server attached over MCP.

**VISUAL:** Screen recording — the captured memory object renders. Highlight in sequence: **Rejected: raise timeout →** *worsened p99*. **Rejected: scale out →** *amplified retry load*. **Rejected: retry w/ backoff →** *caused INC-3391*. Then the provenance footer: `Priya S. · PR #882 · verified`.

> **PRIYA:** It captures the decision trail — including the three things that *didn't* work, and why.
>
> I didn't write a wiki page. I didn't file an ADR. I didn't document anything.
>
> I just did my job.

---

## SCENE 7 — THE PAYOFF
**3:00 – 3:35**

**CARD:** `SAME PROMPT. SAME MODEL. ONE DIFFERENCE.`

**VISUAL:** Split screen. Left = Scene 4's answer, greyed back. Right = live, MARCO retypes the identical prompt.

**VISUAL:** New answer streams in:

> ⚠️ **Don't add retries here.** Retries against `pricing-service` under load amplify the failure — this caused INC-3391 (40 min outage). Use a circuit breaker and fail fast.
> *Already tried and rejected:* raising the timeout, scaling out.
> *Source: Priya S., orders-api PR #882.*

**VISUAL:** Cut to MARCO, to camera.

> **MARCO:** Two seconds.
>
> From someone I've never met, in a repo I've never opened, about a mistake I was thirty seconds away from making.

---

## SCENE 8 — BEYOND THE IDE
**3:35 – 3:52**

**VISUAL:** PRIYA, laptop, Teams open. She types: *"What do we know about pricing-service reliability?"* The agent returns the same memory — framed as service risk, not code.

> **PRIYA:** And my engineering manager doesn't open an IDE.
>
> Same memory, in Teams — because this is an MCP server wrapped in Agents Toolkit. Not a plugin locked inside one editor.

---

## SCENE 9 — CLOSE
**3:52 – 4:00**

**VISUAL:** Quick cut between both, to camera.

> **MARCO:** Individual velocity? That's solved.
>
> **PRIYA:** Organizational velocity isn't.

**VISUAL:** Black.

**CARD:**
> **Your repo remembers what.**
> **[ASSET NAME] remembers why.**

---

# PRODUCTION NOTES

**Four rules — the video fails without these:**

1. **Scene 4 and Scene 7 must be the same prompt, same model, same UI.** The only variable is your MCP server. That side-by-side *is* the entire proof. Record them back-to-back in one sitting.
2. **Never make Copilot look dumb.** The wrong answer in Scene 4 must look genuinely excellent — the audience must think *"I would have shipped that."* If they think Copilot is bad, you've sold nothing. If they think *they* would have made the same mistake, you've sold everything.
3. **Scene 6 is the commercial heart.** The buying decision hinges on *"Priya did nothing extra."* Linger on that line. Zero capture cost is your entire wedge against wikis and ADRs.
4. **Protect the two silences** — after "It took our checkout down for forty minutes" (0:14) and after "Nobody gave the organization one" (2:20). Don't let the editor tighten them.

**Timing budget:** ~410 spoken words ≈ 2:55 of dialogue, leaving ~65s for screen recordings, cards, and beats. If you overrun, cut from Scene 2's V.O. — never from Scenes 6 or 7.

**Casting:** Use real engineers, not actors. Slightly imperfect delivery reads as credible here; polish reads as an ad.

**B-roll to capture:** latency graph degrading, PR approval, pager alert, the memory object rendering, Teams response.

---

Want me to do a **60-second cut-down** (Scenes 1 → 4 → 5 → 7 → 9) for LinkedIn, or turn this into a **shot list / call sheet** for the recording day?