"""Local filesystem cache for downloaded videos."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import config

logger = logging.getLogger(__name__)


@dataclass
class CacheConfig:
	enabled: bool
	directory: Path
	ttl_seconds: float
	max_items: int


class VideoCache:
	"""Stores recently downloaded files on disk for instant reuse."""

	def __init__(self, cfg: CacheConfig) -> None:
		self._cfg = cfg
		self._dir = cfg.directory
		self._dir.mkdir(parents=True, exist_ok=True)
		self._lock = asyncio.Lock()
		self._last_hit_ts: float | None = None
		self._last_store_ts: float | None = None
		self._hits = 0
		self._misses = 0

	@property
	def enabled(self) -> bool:
		return self._cfg.enabled

	def cache_dir(self) -> Path:
		return self._dir

	async def fetch(self, url: str, output_dir: Path) -> Optional[Path]:
		if not self.enabled:
			return None
		entry_dir = self._entry_dir(url)
		meta = await asyncio.to_thread(self._read_meta, entry_dir)
		if not meta:
			self._misses += 1
			return None
		if self._is_expired(meta):
			await asyncio.to_thread(self._delete_entry, entry_dir)
			self._misses += 1
			return None
		cached_file = entry_dir / meta["file_name"]
		if not cached_file.exists():
			await asyncio.to_thread(self._delete_entry, entry_dir)
			self._misses += 1
			return None
		output_dir.mkdir(parents=True, exist_ok=True)
		dest = output_dir / meta["file_name"]
		if dest.exists():
			stem = dest.stem
			suffix = dest.suffix
			dest = output_dir / f"{stem}-{int(time.time())}{suffix}"
		await asyncio.to_thread(shutil.copy2, cached_file, dest)
		self._hits += 1
		self._last_hit_ts = time.time()
		logger.info("Video cache hit for %s (%s)", url, dest)
		return dest

	async def store(self, url: str, file_path: Path) -> None:
		if not self.enabled or not file_path.exists():
			return
		entry_dir = self._entry_dir(url)
		async with self._lock:
			await asyncio.to_thread(self._prepare_entry_dir, entry_dir)
			dest = entry_dir / file_path.name
			await asyncio.to_thread(shutil.copy2, file_path, dest)
			meta = {
				"url": url,
				"file_name": dest.name,
				"stored_at": time.time(),
				"file_size": dest.stat().st_size,
			}
			meta_path = entry_dir / "meta.json"
			await asyncio.to_thread(meta_path.write_text, json.dumps(meta), "utf-8")
			self._last_store_ts = meta["stored_at"]
			await asyncio.to_thread(self._prune_if_needed)

	def state(self) -> Dict[str, Optional[float | int | str]]:
		return {
			"enabled": self.enabled,
			"dir": str(self._dir),
			"ttl_seconds": self._cfg.ttl_seconds,
			"max_items": self._cfg.max_items,
			"hits": self._hits,
			"misses": self._misses,
			"last_hit_ts": self._last_hit_ts,
			"last_store_ts": self._last_store_ts,
		}

	def _entry_dir(self, url: str) -> Path:
		digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
		return self._dir / digest

	def _is_expired(self, meta: Dict[str, object]) -> bool:
		stored_at = float(meta.get("stored_at", 0))
		return (time.time() - stored_at) > self._cfg.ttl_seconds

	def _read_meta(self, entry_dir: Path) -> Optional[Dict[str, object]]:
		meta_path = entry_dir / "meta.json"
		if not meta_path.exists() or not entry_dir.is_dir():
			return None
		try:
			return json.loads(meta_path.read_text("utf-8"))
		except Exception:
			return None

	def _prepare_entry_dir(self, entry_dir: Path) -> None:
		if entry_dir.exists():
			shutil.rmtree(entry_dir, ignore_errors=True)
		entry_dir.mkdir(parents=True, exist_ok=True)

	def _delete_entry(self, entry_dir: Path) -> None:
		if entry_dir.exists():
			shutil.rmtree(entry_dir, ignore_errors=True)

	def _prune_if_needed(self) -> None:
		entries: list[tuple[float, Path]] = []
		for entry in self._dir.iterdir():
			meta = self._read_meta(entry)
			if not meta:
				self._delete_entry(entry)
				continue
			entries.append((float(meta.get("stored_at", 0)), entry))
		entries.sort(key=lambda item: item[0], reverse=True)
		for _, entry in entries[self._cfg.max_items :]:
			self._delete_entry(entry)


_cache: VideoCache | None = None


def _build_cache() -> VideoCache:
	global _cache
	cfg = CacheConfig(
		enabled=bool(config.VIDEO_CACHE_ENABLED and config.VIDEO_CACHE_DIR),
		directory=Path(config.VIDEO_CACHE_DIR or "./tmp/video_cache"),
		ttl_seconds=float(getattr(config, "VIDEO_CACHE_TTL_SECONDS", 3600)),
		max_items=int(getattr(config, "VIDEO_CACHE_MAX_ITEMS", 200)),
	)
	_cache = VideoCache(cfg)
	return _cache


def _get_cache() -> VideoCache:
	if _cache is None:
		return _build_cache()
	return _cache


def is_enabled() -> bool:
	return _get_cache().enabled


def get_state() -> Dict[str, Optional[float | int | str]]:
	return _get_cache().state()


async def get_cached_copy(url: str, output_dir: Path) -> Optional[Path]:
	try:
		return await _get_cache().fetch(url, output_dir)
	except Exception:
		logger.debug("Video cache fetch failed", exc_info=True)
		return None


async def store_copy(url: str, file_path: Path) -> None:
	try:
		await _get_cache().store(url, file_path)
	except Exception:
		logger.debug("Video cache store failed", exc_info=True)


def reset_for_tests() -> None:  # pragma: no cover - helper for test isolation
	global _cache
	_cache = None


__all__ = [
	"get_cached_copy",
	"store_copy",
	"is_enabled",
	"get_state",
	"reset_for_tests",
	"VideoCache",
]
