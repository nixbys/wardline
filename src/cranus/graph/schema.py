"""Knowledge-graph ontology (report 4.5): a light, explicit schema of node
labels and relationship types keeps the graph coherent and queryable.
"""

from __future__ import annotations

NODE_LABEL = "Entity"  # all entities share one label; `type` property distinguishes Person/Organization/...

ENTITY_TYPES = ("Person", "Organization", "Place", "Product", "Other")

RELATION_TYPES = (
    "FOUNDED",
    "CO_FOUNDED_WITH",
    "SUBSIDIARY_OF",
    "ACQUIRED",
    "EMPLOYED_BY",
    "LOCATED_IN",
    "RELATED_TO",
)

CONSTRAINTS_CYPHER = [
    "CREATE CONSTRAINT entity_id_unique IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
]
