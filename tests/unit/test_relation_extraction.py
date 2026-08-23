from wardline.graph.ner import Mention
from wardline.graph.relation_extraction import extract_relations


def _mention(text: str, needle: str, ner_type: str, occurrence: int = 0) -> Mention:
    idx = -1
    for _ in range(occurrence + 1):
        idx = text.index(needle, idx + 1)
    return Mention(span_text=needle, span_start=idx, span_end=idx + len(needle), ner_type=ner_type, confidence=0.9)


def test_founded_does_not_link_unrelated_bystanders():
    # Regression target: the old sentence-scoped keyword-only version linked
    # *every* Person to *every* Organization in a trigger sentence. Here
    # only Carol founded Acme Corp -- Dave is a bystander and Beta Inc is
    # mentioned in an unrelated clause about Carol's advisory role.
    text = (
        "Investors including Dave met with Carol, who founded Acme Corp "
        "and also serves as an advisor to Beta Inc."
    )
    mentions = [
        _mention(text, "Dave", "Person"),
        _mention(text, "Carol", "Person"),
        _mention(text, "Acme Corp", "Organization"),
        _mention(text, "Beta Inc", "Organization"),
    ]
    relations = extract_relations(text, mentions)
    founded = [r for r in relations if r.type == "FOUNDED"]
    assert len(founded) == 1
    assert founded[0].from_mention.span_text == "Carol"
    assert founded[0].to_mention.span_text == "Acme Corp"


def test_co_founded_links_both_founders_via_conjunction():
    text = "Alice and Bob co-founded Acme Corp together."
    mentions = [
        _mention(text, "Alice", "Person"),
        _mention(text, "Bob", "Person"),
        _mention(text, "Acme Corp", "Organization"),
    ]
    relations = extract_relations(text, mentions)
    founded = {(r.from_mention.span_text, r.to_mention.span_text) for r in relations if r.type == "FOUNDED"}
    assert founded == {("Alice", "Acme Corp"), ("Bob", "Acme Corp")}
    cofounders = {
        frozenset((r.from_mention.span_text, r.to_mention.span_text))
        for r in relations
        if r.type == "CO_FOUNDED_WITH"
    }
    assert frozenset(("Alice", "Bob")) in cofounders


def test_single_subject_co_founded_falls_back_when_unambiguous():
    # The small model's parser occasionally mangles a hyphenated
    # "co-founded" right after a lone proper-noun subject. With exactly one
    # person and one org candidate there's nothing to conflate, so the
    # narrow fallback should still recover the relation.
    text = "Carol co-founded Acme Corp."
    mentions = [_mention(text, "Carol", "Person"), _mention(text, "Acme Corp", "Organization")]
    relations = extract_relations(text, mentions)
    assert any(
        r.type == "FOUNDED" and r.from_mention.span_text == "Carol" and r.to_mention.span_text == "Acme Corp"
        for r in relations
    )


def test_subsidiary_of_appositive():
    text = "Acme Corp, a subsidiary of Global Inc, announced layoffs."
    mentions = [_mention(text, "Acme Corp", "Organization"), _mention(text, "Global Inc", "Organization")]
    relations = extract_relations(text, mentions)
    assert any(
        r.type == "SUBSIDIARY_OF" and r.from_mention.span_text == "Acme Corp" and r.to_mention.span_text == "Global Inc"
        for r in relations
    )


def test_subsidiary_owned_by_passive():
    text = "Acme Corp is owned by Global Inc."
    mentions = [_mention(text, "Acme Corp", "Organization"), _mention(text, "Global Inc", "Organization")]
    relations = extract_relations(text, mentions)
    assert any(
        r.type == "SUBSIDIARY_OF" and r.from_mention.span_text == "Acme Corp" and r.to_mention.span_text == "Global Inc"
        for r in relations
    )


def test_acquired_active_and_passive_agree_on_direction():
    active_text = "Acme Corp acquired Beta Inc last year."
    active_mentions = [
        _mention(active_text, "Acme Corp", "Organization"),
        _mention(active_text, "Beta Inc", "Organization"),
    ]
    passive_text = "Beta Inc was acquired by Acme Corp last year."
    passive_mentions = [
        _mention(passive_text, "Beta Inc", "Organization"),
        _mention(passive_text, "Acme Corp", "Organization"),
    ]

    for text, mentions in [(active_text, active_mentions), (passive_text, passive_mentions)]:
        relations = extract_relations(text, mentions)
        acquired = [r for r in relations if r.type == "ACQUIRED"]
        assert len(acquired) == 1
        # ACQUIRED direction is (target, acquirer) in both active and passive phrasing.
        assert acquired[0].from_mention.span_text == "Beta Inc"
        assert acquired[0].to_mention.span_text == "Acme Corp"
