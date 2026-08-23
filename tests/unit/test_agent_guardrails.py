from wardline.agent.guardrails import AgentBudget, estimate_tokens


def test_steps_exhausted_after_max_steps():
    budget = AgentBudget(max_steps=2, max_total_tokens=10_000)
    assert not budget.steps_exhausted()
    budget.record_step(tokens=10)
    assert not budget.steps_exhausted()
    budget.record_step(tokens=10)
    assert budget.steps_exhausted()


def test_tokens_exhausted_once_over_budget():
    budget = AgentBudget(max_steps=100, max_total_tokens=50)
    budget.record_step(tokens=60)
    assert budget.tokens_exhausted()


def test_duplicate_call_detection():
    budget = AgentBudget(max_steps=10, max_total_tokens=10_000)
    assert not budget.is_duplicate_call("search_text", {"query": "who founded Airbnb"})
    assert budget.is_duplicate_call("search_text", {"query": "who founded Airbnb"})
    assert not budget.is_duplicate_call("search_text", {"query": "a different query"})


def test_estimate_tokens_is_positive_for_nonempty_text():
    assert estimate_tokens("a short phrase") > 0
    assert estimate_tokens("") == 1
