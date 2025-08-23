from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from app.core.data.repository import get_data_layer

T = TypeVar("T", bound=BaseModel)


class Queryable(Protocol):
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    async def fetchrow(self, query: str, *args: Any) -> Any | None: ...
    async def fetchval(self, query: str, *args: Any) -> Any: ...
    async def execute(self, query: str, *args: Any) -> str: ...


class BaseRepository[T](ABC):
    def __init__(self, table_name: str, db: Queryable | None = None):
        self.db: Queryable = db or get_data_layer()
        self.table_name = table_name

    @abstractmethod
    def _to_model(self, record: dict[str, Any]) -> T: ...

    @abstractmethod
    def _from_model(self, model: T) -> dict[str, Any]: ...

    async def find_by_id(self, id: str) -> T | None:
        query = f"SELECT * FROM {self.table_name} WHERE id = $1"
        record = await self.db.fetchrow(query, id)
        return self._to_model(dict(record)) if record else None

    async def find_all(
        self,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "created_at DESC",
    ) -> list[T]:
        allowed_order_by = [
            "created_at DESC",
            "created_at ASC",
            "updated_at DESC",
            "updated_at ASC",
            "id DESC",
            "id ASC",
        ]
        if order_by not in allowed_order_by:
            order_by = "created_at DESC"
        query = f"SELECT * FROM {self.table_name} ORDER BY {order_by} LIMIT $1 OFFSET $2"
        records = await self.db.fetch(query, limit, offset)
        return [self._to_model(dict(record)) for record in records]

    async def create(self, model: T) -> T:
        data = self._from_model(model)
        data["id"] = str(uuid.uuid4())
        data["created_at"] = datetime.utcnow()
        data["updated_at"] = datetime.utcnow()
        columns = ", ".join(data.keys())
        placeholders = ", ".join(f"${i + 1}" for i in range(len(data)))
        query = f"INSERT INTO {self.table_name} ({columns}) VALUES ({placeholders}) RETURNING *"
        record = await self.db.fetchrow(query, *data.values())
        return self._to_model(dict(record))

    async def update(self, id: str, updates: dict[str, Any]) -> T | None:
        updates["updated_at"] = datetime.utcnow()
        set_clause = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(updates.keys()))
        query = f"UPDATE {self.table_name} SET {set_clause} WHERE id = $1 RETURNING *"
        record = await self.db.fetchrow(query, id, *updates.values())
        return self._to_model(dict(record)) if record else None

    async def delete(self, id: str) -> bool:
        query = f"DELETE FROM {self.table_name} WHERE id = $1"
        result = await self.db.execute(query, id)
        return "DELETE 1" in result

    async def count(self, where: dict[str, Any] | None = None) -> int:
        if where:
            conditions = " AND ".join(f"{k} = ${i + 1}" for i, k in enumerate(where.keys()))
            query = f"SELECT COUNT(*) FROM {self.table_name} WHERE {conditions}"
            return await self.db.fetchval(query, *where.values())
        query = f"SELECT COUNT(*) FROM {self.table_name}"
        return await self.db.fetchval(query)

    async def exists(self, where: dict[str, Any]) -> bool:
        conditions = " AND ".join(f"{k} = ${i + 1}" for i, k in enumerate(where.keys()))
        query = f"SELECT EXISTS(SELECT 1 FROM {self.table_name} WHERE {conditions})"
        return await self.db.fetchval(query, *where.values())
