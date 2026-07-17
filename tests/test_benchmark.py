"""The hypothesis, as a regression test: warm must answer every scenario
correctly AND cost materially less than cold."""

from benchmark.bench import run


def test_warm_answers_all_scenarios_and_saves_tokens():
    results, seed_cost = run()
    assert results, "no scenarios ran"
    failures = [r.scenario.id for r in results if not r.answered]
    assert not failures, f"warm path failed to answer: {failures}"

    cold_total = sum(r.cold_tokens for r in results)
    warm_total = sum(r.warm_tokens for r in results)
    assert warm_total < cold_total * 0.5, (
        f"saving collapsed: cold={cold_total}, warm={warm_total}"
    )
    # One-time write cost amortizes within a single extra engineer.
    assert seed_cost < cold_total - warm_total


def test_every_scenario_saves_individually():
    results, _ = run()
    for result in results:
        assert result.warm_tokens < result.cold_tokens, result.scenario.id
