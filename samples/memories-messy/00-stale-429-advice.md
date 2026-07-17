---
path: /gotchas/429-rate-limit.md
category: gotcha
tags: testing, 429
---
# Bank simulator 429s in parallel test runs

Getting 429 Too Many Requests from the simulator when running tests with
`-n auto`. Workaround for now: rerun the failed tests serially, or add a
sleep between integration tests. Haven't found the real fix yet.
