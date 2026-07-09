"""Clustering (report 4.5): resolves pairwise scores into clusters that each
represent one real entity, via connected components over high-confidence
pairs.
"""

from __future__ import annotations

import networkx as nx


def cluster_pairs(pairs: list[tuple[str, str, float]], threshold: float) -> list[set[str]]:
    graph = nx.Graph()
    for a, b, score in pairs:
        graph.add_node(a)
        graph.add_node(b)
        if score >= threshold:
            graph.add_edge(a, b, weight=score)
    return [component for component in nx.connected_components(graph) if len(component) > 1]
