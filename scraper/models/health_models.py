from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional


@dataclass
class DataPoint:
    """One Google Health data point, stored with its raw JSON payload."""
    dataType: str
    pointId: str
    payload: dict[str, Any] = field(default_factory=dict)
    startTime: Optional[datetime] = None
    endTime: Optional[datetime] = None
    recordDate: Optional[date] = None


@dataclass
class SyncState:
    """Per data type checkpoint: everything up to lastSyncedAt has been fetched."""
    dataType: str
    lastSyncedAt: Optional[datetime] = None
    lastStatus: Optional[str] = None
    lastError: Optional[str] = None
    updatedAt: Optional[datetime] = None
