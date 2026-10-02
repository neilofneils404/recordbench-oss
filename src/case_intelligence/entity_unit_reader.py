"""Bounded transient offsets for discovery over existing UTF-8 unit containers.

No extracted text or persistent index is cached. The source mutation guard is
owned by the caller; file identity is checked independently before and after I/O.
"""
from collections import OrderedDict
import json
import os
import stat
import threading

from .pilot_uploads import PilotUnit
from .unit_stream import iter_unit_records, MAX_UNIT_RECORD_CHARS

READ_BYTES = 64 * 1024


class EntityUnitReader:
    def __init__(self):
        self._indexes = OrderedDict()
        self._lock = threading.RLock()

    @staticmethod
    def identity(metadata):
        return (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns)

    @staticmethod
    def _read_span(raw, length, read_check):
        # Bounded reads so a caller polling read_check can abandon a large record.
        if read_check is None:
            return raw.read(length)
        chunks, remaining = [], length
        while remaining > 0:
            read_check(length - remaining)
            chunk = raw.read(min(READ_BYTES, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b''.join(chunks)

    def iter_selected(self, store, document, ordinals, *, read_check=None):
        requested = sorted(set(ordinals))
        if not requested:
            return
        if getattr(document, 'units', None):
            for ordinal in requested:
                if 1 <= ordinal <= len(document.units):
                    yield ordinal, PilotUnit(**document.units[ordinal - 1])
            return
        name = getattr(document, 'units_file', '')
        if not name:
            wanted = set(requested)
            parsed = (document.iter_parsed_units(read_check=read_check) if read_check is not None
                      else document.iter_parsed_units())
            for ordinal, unit in enumerate(parsed, 1):
                if ordinal in wanted:
                    yield ordinal, unit
                if ordinal >= requested[-1]:
                    break
            return
        if not store._units_file_is_safe(name):
            raise RuntimeError('Derived searchable text is unavailable.')
        path = store.derived / name
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as raw:
            metadata = os.fstat(raw.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise RuntimeError('Derived searchable text is unavailable.')
            identity = self.identity(metadata)
            key = (str(path), identity)
            with self._lock:
                offsets = self._indexes.get(key)
                if offsets is not None:
                    self._indexes.move_to_end(key)
            if offsets is None:
                import io
                spans = []
                def record_span(start, end):
                    if len(spans) >= 20000:
                        raise ValueError('Discovery unit index exceeds the existing unit ceiling.')
                    spans.append((start, end))
                # newline='' retains serialized CRLF bytes for exact offsets.
                with io.TextIOWrapper(os.fdopen(os.dup(raw.fileno()), 'rb'), encoding='utf-8', newline='') as stream:
                    # read_check runs for every bounded read, so a caller can abandon a long index build.
                    for record in iter_unit_records(stream, record_span=record_span, read_check=read_check):
                        PilotUnit(**record)
                if self.identity(os.fstat(raw.fileno())) != identity:
                    raise RuntimeError('Derived searchable text changed during indexing.')
                offsets = tuple(spans)
                with self._lock:
                    # At most 20,000 offsets and eight source identities total.
                    while self._indexes and (len(self._indexes) >= 8 or
                            sum(len(value) for value in self._indexes.values()) + len(offsets) > 20000):
                        self._indexes.popitem(last=False)
                    self._indexes[key] = offsets
            for ordinal in requested:
                if not 1 <= ordinal <= len(offsets):
                    continue
                start, end = offsets[ordinal - 1]
                if end - start > 4 * MAX_UNIT_RECORD_CHARS:
                    raise ValueError('Derived searchable unit exceeds its serialized bound.')
                raw.seek(start)
                record = json.loads(self._read_span(raw, end - start, read_check))
                if self.identity(os.fstat(raw.fileno())) != identity:
                    raise RuntimeError('Derived searchable text changed during discovery.')
                yield ordinal, PilotUnit(**record)
