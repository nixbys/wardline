"""Import every model module so `Base.metadata` is fully populated for Alembic
autogenerate and for `Base.metadata.create_all()` in tests.
"""

from cranus.storage.models.base import Base
from cranus.storage.models.chunks import Chunk
from cranus.storage.models.documents import Document
from cranus.storage.models.edges import Edge
from cranus.storage.models.engagements import Engagement
from cranus.storage.models.entities import Entity
from cranus.storage.models.entity_resolution import (
    EdgeCandidate,
    EntityMention,
    EntityResolutionReview,
)
from cranus.storage.models.feedback import Feedback
from cranus.storage.models.governance import ApiKey, AuditEvent, SystemSetting, User
from cranus.storage.models.ingestion import IngestionJob, Source

__all__ = [
    "ApiKey",
    "AuditEvent",
    "Base",
    "Chunk",
    "Document",
    "Edge",
    "EdgeCandidate",
    "Engagement",
    "Entity",
    "EntityMention",
    "EntityResolutionReview",
    "Feedback",
    "IngestionJob",
    "Source",
    "SystemSetting",
    "User",
]
