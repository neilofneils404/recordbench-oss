"""Incrementally read the existing derived-unit JSON format without a file copy."""
from __future__ import annotations
import json


# A 10-million-character unit remains admissible even if every Unicode code
# point is escaped as a surrogate pair (12 JSON characters), plus metadata.
MAX_UNIT_RECORD_CHARS = 120_065_536
READ_CHARS = 64 * 1024


class UnitRecordLimit(ValueError):
    pass


class _Reader:
    def __init__(self, stream, maximum, budget_check, read_check, track_bytes=False):
        self.stream, self.maximum = stream, maximum
        self.budget_check, self.read_check = budget_check, read_check
        self.buffer, self.position, self.ended = '', 0, False
        self.byte_base, self.track_bytes = 0, track_bytes

    def check(self):
        if self.budget_check is not None:
            self.budget_check()

    def peek(self):
        if self.position == len(self.buffer) and not self.ended:
            self.check()
            if self.track_bytes:
                self.byte_base += len(self.buffer.encode('utf-8'))
            self.buffer = self.stream.read(READ_CHARS)
            self.position = 0
            self.ended = not self.buffer
            # Charge serialized input and time before retaining or decoding a
            # record. Callback failures deliberately propagate unchanged.
            if self.read_check is not None:
                self.read_check(len(self.buffer))
            self.check()
        return self.buffer[self.position:self.position + 1]

    def byte_position(self):
        return self.byte_base + len(self.buffer[:self.position].encode('utf-8'))

    def trim(self):
        while self.peek() in {' ', '\t', '\r', '\n'}:
            self.position += 1

    def token(self, expected):
        self.trim()
        if self.peek() != expected:
            raise ValueError('Malformed derived text container')
        self.position += 1

    def value(self):
        self.trim()
        first = self.peek()
        if not first:
            raise ValueError('Malformed derived text value')
        compound, quoted = first in '{[', first == '"'
        depth, in_string, escaped = 0, False, False
        chunks, count, complete = [], 0, False
        while not complete:
            if not self.peek():
                if compound or quoted:
                    raise ValueError('Malformed derived text value')
                break
            start = self.position
            # Frame one complete value without repeatedly JSON-decoding its
            # growing prefix. Each pass scans at most one bounded read buffer.
            while self.position < len(self.buffer):
                char = self.buffer[self.position]
                if not compound and not quoted and char in ',]} \t\r\n':
                    complete = True
                    break
                self.position += 1
                if in_string:
                    if escaped:
                        escaped = False
                    elif char == '\\':
                        escaped = True
                    elif char == '"':
                        in_string = False
                        if quoted:
                            complete = True
                elif char == '"':
                    in_string = True
                elif char in '{[':
                    depth += 1
                    if depth > 64:
                        raise ValueError('Derived text nesting is too deep')
                elif char in '}]':
                    depth -= 1
                    complete = depth <= 0
                if complete:
                    break
            count += self.position - start
            if count > self.maximum:
                raise UnitRecordLimit('Derived text unit record exceeds the bounded reader limit; its inventory remains unresolved.')
            chunks.append(self.buffer[start:self.position])
            self.check()
        raw = ''.join(chunks)
        # The bound is checked before this sole decode, including corrupt or
        # oversized first records. I/O and a bounded decode are cooperative.
        self.check()
        result, end = json.JSONDecoder().raw_decode(raw)
        self.check()
        if end != len(raw):
            raise ValueError('Malformed derived text value')
        return result


def iter_unit_records(stream, *, max_record_chars=MAX_UNIT_RECORD_CHARS,
                      budget_check=None, read_check=None, record_span=None):
    """Yield records with optional per-read/decode and serialized-input budgets."""
    if type(max_record_chars) is not int or max_record_chars < 1:
        raise ValueError('Derived text record bound must be positive')
    reader = _Reader(stream, max_record_chars, budget_check, read_check, record_span is not None)
    reader.token('{')
    version, seen = None, set()
    while True:
        key = reader.value()
        if not isinstance(key, str) or key not in {'version', 'units'} or key in seen:
            raise ValueError('Unexpected derived text field')
        seen.add(key)
        reader.token(':')
        if key == 'version':
            version = reader.value()
        else:
            reader.token('[')
            reader.trim()
            if reader.peek() == ']':
                reader.token(']')
            else:
                while True:
                    reader.trim()
                    start = reader.byte_position() if record_span is not None else 0
                    record = reader.value()
                    if record_span is not None:
                        record_span(start, reader.byte_position())
                    if not isinstance(record, dict):
                        raise ValueError('Malformed derived text unit')
                    yield record
                    reader.trim()
                    if reader.peek() == ']':
                        reader.token(']')
                        break
                    reader.token(',')
        reader.trim()
        if reader.peek() == '}':
            reader.token('}')
            break
        reader.token(',')
    reader.trim()
    if reader.peek() or seen != {'version', 'units'} or type(version) is not int or version != 1:
        raise ValueError('Invalid derived text container')
