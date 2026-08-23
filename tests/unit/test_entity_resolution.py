from wardline.graph.entity_resolution.blocking import block_key
from wardline.graph.entity_resolution.clustering import cluster_pairs
from wardline.graph.entity_resolution.scoring import score_pair


def test_exact_name_match_scores_near_one_with_no_attributes():
    # Regression test: the weighted average used to always reserve 10% for
    # attribute overlap, so even an exact match capped at 0.9 when no
    # attributes were supplied (which is always, in this build) -- every
    # mention landed just under the 0.92 high-confidence merge threshold.
    score = score_pair("Chesky", "Chesky")
    assert score == 1.0


def test_similar_names_score_higher_than_dissimilar():
    similar = score_pair("Brian Chesky", "Brian Chesky Jr.")
    dissimilar = score_pair("Brian Chesky", "Nathan Blecharczyk")
    assert similar > dissimilar


def test_shared_attributes_affect_score():
    same_attrs = score_pair("J. Smith", "John Smith", {"born": "1980"}, {"born": "1980"})
    diff_attrs = score_pair("J. Smith", "John Smith", {"born": "1980"}, {"born": "1990"})
    assert same_attrs > diff_attrs


def test_block_key_groups_same_first_token():
    assert block_key("Person", "Chesky") == block_key("Person", "Chesky")
    assert block_key("Person", "Brian Chesky") != block_key("Person", "Chesky")


def test_cluster_pairs_groups_above_threshold():
    pairs = [("a", "b", 0.95), ("b", "c", 0.95), ("d", "e", 0.4)]
    clusters = cluster_pairs(pairs, threshold=0.9)

    assert {"a", "b", "c"} in clusters
    assert not any({"d", "e"} <= c for c in clusters)
