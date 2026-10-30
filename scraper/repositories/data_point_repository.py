from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterator, List

from scraper.models.health_models import DataPoint


class DataPointRepository(ABC):
    """Abstract repository interface for DataPoint persistence."""

    @abstractmethod
    def upsert_many(self, data_points: List[DataPoint]) -> int:
        """Insert or update data points by (dataType, pointId); return rows written."""
        pass

    @abstractmethod
    def count(self, data_type: str) -> int:
        """Return how many data points are stored for a data type."""
        pass

    @abstractmethod
    def latest_start_time(self, data_type: str) -> datetime | None:
        """Return the newest startTime stored for a data type."""
        pass

    @abstractmethod
    def iter_points(self, data_type: str, batch_size: int = 5000) -> Iterator[DataPoint]:
        """Stream every stored raw point of a data type (used to rebuild the typed tables)."""
        pass
