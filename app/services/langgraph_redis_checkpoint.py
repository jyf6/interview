from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any
from urllib.parse import quote

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
)
from redis.asyncio import Redis

from app.core.config import settings


class RedisCheckpointSaver(BaseCheckpointSaver[str]):
    """Small async Redis checkpointer for the interview LangGraph.

    The project only needs async graph execution. Sync methods are intentionally
    unsupported so web requests never block on Redis I/O.
    """

    def __init__(
        self,
        redis: Redis,
        *,
        key_prefix: str = "interview:langgraph",
        ttl_seconds: int | None = None,
    ) -> None:
        super().__init__()
        self.redis = redis
        self.key_prefix = key_prefix.rstrip(":")
        self.ttl_seconds = ttl_seconds if ttl_seconds is not None else settings.session_ttl_seconds

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        raise NotImplementedError("Use async LangGraph checkpoint methods with RedisCheckpointSaver.")

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        raise NotImplementedError("Use async LangGraph checkpoint methods with RedisCheckpointSaver.")

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        raise NotImplementedError("Use async LangGraph checkpoint methods with RedisCheckpointSaver.")

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        raise NotImplementedError("Use async LangGraph checkpoint methods with RedisCheckpointSaver.")

    def delete_thread(self, thread_id: str) -> None:
        raise NotImplementedError("Use async LangGraph checkpoint methods with RedisCheckpointSaver.")

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id, checkpoint_ns = self._config_identity(config)
        storage = await self._load_json(self._storage_key(thread_id, checkpoint_ns), {})
        checkpoint_id = get_checkpoint_id(config)
        if checkpoint_id:
            saved = storage.get(checkpoint_id)
        else:
            checkpoint_id = max(storage.keys(), default="")
            saved = storage.get(checkpoint_id) if checkpoint_id else None
        if not saved or not checkpoint_id:
            return None

        checkpoint = self.serde.loads_typed(self._unpack_typed(saved["checkpoint"]))
        metadata = self.serde.loads_typed(self._unpack_typed(saved["metadata"]))
        checkpoint = {
            **checkpoint,
            "channel_values": await self._load_blobs(
                thread_id,
                checkpoint_ns,
                checkpoint.get("channel_versions", {}),
            ),
        }
        writes = await self._load_json(self._writes_key(thread_id, checkpoint_ns, checkpoint_id), {})
        pending_writes = [
            (item["task_id"], item["channel"], self.serde.loads_typed(self._unpack_typed(item["value"])))
            for _, item in sorted(writes.items())
        ]
        parent_checkpoint_id = saved.get("parent_checkpoint_id")
        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": checkpoint_id,
                }
            },
            checkpoint=checkpoint,
            metadata=metadata,
            pending_writes=pending_writes,
            parent_config=(
                {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": parent_checkpoint_id,
                    }
                }
                if parent_checkpoint_id
                else None
            ),
        )

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        if not config:
            return
        thread_id, checkpoint_ns = self._config_identity(config)
        storage = await self._load_json(self._storage_key(thread_id, checkpoint_ns), {})
        before_id = get_checkpoint_id(before) if before else None
        yielded = 0
        for checkpoint_id in sorted(storage.keys(), reverse=True):
            if before_id and checkpoint_id >= before_id:
                continue
            tuple_ = await self.aget_tuple(
                {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": checkpoint_id,
                    }
                }
            )
            if tuple_ is None:
                continue
            if filter and any(tuple_.metadata.get(key) != value for key, value in filter.items()):
                continue
            yield tuple_
            yielded += 1
            if limit is not None and yielded >= limit:
                break

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        thread_id, checkpoint_ns = self._config_identity(config)
        checkpoint_copy = checkpoint.copy()
        values: dict[str, Any] = checkpoint_copy.pop("channel_values")  # type: ignore[misc]
        blobs = await self._load_json(self._blobs_key(thread_id, checkpoint_ns), {})
        for channel, version in new_versions.items():
            blob_key = self._blob_id(channel, version)
            blobs[blob_key] = (
                self._pack_typed(self.serde.dumps_typed(values[channel]))
                if channel in values
                else self._pack_typed(("empty", b""))
            )
        await self._store_json(self._blobs_key(thread_id, checkpoint_ns), blobs)

        storage = await self._load_json(self._storage_key(thread_id, checkpoint_ns), {})
        storage[checkpoint["id"]] = {
            "checkpoint": self._pack_typed(self.serde.dumps_typed(checkpoint_copy)),
            "metadata": self._pack_typed(self.serde.dumps_typed(get_checkpoint_metadata(config, metadata))),
            "parent_checkpoint_id": config["configurable"].get("checkpoint_id"),
        }
        await self._store_json(self._storage_key(thread_id, checkpoint_ns), storage)
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id, checkpoint_ns = self._config_identity(config)
        checkpoint_id = config["configurable"]["checkpoint_id"]
        key = self._writes_key(thread_id, checkpoint_ns, checkpoint_id)
        stored = await self._load_json(key, {})
        for idx, (channel, value) in enumerate(writes):
            write_idx = WRITES_IDX_MAP.get(channel, idx)
            write_key = f"{task_id}:{write_idx}"
            if write_idx >= 0 and write_key in stored:
                continue
            stored[write_key] = {
                "task_id": task_id,
                "channel": channel,
                "value": self._pack_typed(self.serde.dumps_typed(value)),
                "task_path": task_path,
            }
        await self._store_json(key, stored)

    async def adelete_thread(self, thread_id: str) -> None:
        index_key = self._thread_index_key(thread_id)
        raw_keys = await self._load_json(index_key, [])
        for key in raw_keys:
            await self.redis.delete(key)
        await self.redis.delete(index_key)

    async def _load_blobs(
        self,
        thread_id: str,
        checkpoint_ns: str,
        versions: ChannelVersions,
    ) -> dict[str, Any]:
        blobs = await self._load_json(self._blobs_key(thread_id, checkpoint_ns), {})
        result: dict[str, Any] = {}
        for channel, version in versions.items():
            packed = blobs.get(self._blob_id(channel, version))
            if not packed:
                continue
            typed_value = self._unpack_typed(packed)
            if typed_value[0] == "empty":
                continue
            result[channel] = self.serde.loads_typed(typed_value)
        return result

    async def _load_json(self, key: str, default: Any) -> Any:
        raw = await self.redis.get(key)
        if not raw:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default

    async def _store_json(self, key: str, value: Any) -> None:
        await self.redis.set(key, json.dumps(value, ensure_ascii=False), ex=self.ttl_seconds)
        await self._index_key(key)

    async def _index_key(self, key: str) -> None:
        index_key = self._thread_index_key_from_data_key(key)
        if not index_key:
            return
        keys = await self._load_json(index_key, [])
        if key not in keys:
            keys.append(key)
        await self.redis.set(index_key, json.dumps(keys, ensure_ascii=False), ex=self.ttl_seconds)

    @staticmethod
    def _pack_typed(value: tuple[str, bytes]) -> list[str]:
        return [value[0], base64.b64encode(value[1]).decode("ascii")]

    @staticmethod
    def _unpack_typed(value: list[str]) -> tuple[str, bytes]:
        return value[0], base64.b64decode(value[1].encode("ascii"))

    @staticmethod
    def _blob_id(channel: str, version: Any) -> str:
        return f"{channel}:{version}"

    @staticmethod
    def _safe(value: str) -> str:
        return quote(value, safe="")

    def _config_identity(self, config: RunnableConfig) -> tuple[str, str]:
        configurable = config.get("configurable", {})
        thread_id = str(configurable["thread_id"])
        checkpoint_ns = str(configurable.get("checkpoint_ns", ""))
        return thread_id, checkpoint_ns

    def _thread_index_key(self, thread_id: str) -> str:
        return f"{self.key_prefix}:index:{self._safe(thread_id)}"

    def _thread_index_key_from_data_key(self, key: str) -> str | None:
        prefix = f"{self.key_prefix}:"
        if not key.startswith(prefix):
            return None
        parts = key[len(prefix) :].split(":", 1)
        if not parts:
            return None
        return f"{self.key_prefix}:index:{parts[0]}"

    def _storage_key(self, thread_id: str, checkpoint_ns: str) -> str:
        return f"{self.key_prefix}:{self._safe(thread_id)}:{self._safe(checkpoint_ns)}:storage"

    def _blobs_key(self, thread_id: str, checkpoint_ns: str) -> str:
        return f"{self.key_prefix}:{self._safe(thread_id)}:{self._safe(checkpoint_ns)}:blobs"

    def _writes_key(self, thread_id: str, checkpoint_ns: str, checkpoint_id: str) -> str:
        return f"{self.key_prefix}:{self._safe(thread_id)}:{self._safe(checkpoint_ns)}:writes:{self._safe(checkpoint_id)}"
