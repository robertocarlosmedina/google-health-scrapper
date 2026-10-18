from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional

from scraper.models.health_models import SyncState


class SyncStateRepository(ABC):
    """Abstract repository interface for per data type sync checkpoints."""

    @abstractmethod
    def get(self, data_type: str) -> Optional[SyncState]:
        """Return the checkpoint for a data type, or None if never synced."""
        pass

    @abstractmethod
    def list_all(self) -> List[SyncState]:
        """Return every stored checkpoint."""
        pass

    @abstractmethod
    def mark_success(self, data_type: str, synced_until: datetime) -> None:
        """Advance the checkpoint after a successful sync."""
        pass

    @abstractmethod
    def mark_failure(self, data_type: str, error: str) -> None:
        """Record a failed sync without moving the checkpoint."""
        pass
