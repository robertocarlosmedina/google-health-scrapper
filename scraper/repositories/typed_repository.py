from abc import ABC, abstractmethod


class TypedRepository(ABC):
    @abstractmethod
    def upsert_rows(self, table: str, rows: list[dict]) -> int:
        """Insert or update rows of a typed table by its primary key; return rows written."""
        pass
