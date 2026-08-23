"""Import every model module so `Base.metadata` is fully populated for Alembic
autogenerate and for `Base.metadata.create_all()` in tests.
"""

from wardline.storage.models.base import Base
from wardline.storage.models.billing import Subscription
from wardline.storage.models.chunks import Chunk
from wardline.storage.models.documents import Document
from wardline.storage.models.edges import Edge
from wardline.storage.models.engagements import Engagement
from wardline.storage.models.entities import Entity
from wardline.storage.models.entity_resolution import (
    EdgeCandidate,
    EntityMention,
    EntityResolutionReview,
)
from wardline.storage.models.feedback import Feedback
from wardline.storage.models.governance import (
    ApiKey,
    AuditEvent,
    AuthToken,
    RecoveryCode,
    SystemSetting,
    User,
)
from wardline.storage.models.ingestion import IngestionJob, Source

__all__ = [
    "ApiKey",
    "AuditEvent",
    "AuthToken",
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
    "RecoveryCode",
    "Source",
    "Subscription",
    "SystemSetting",
    "User",
]
