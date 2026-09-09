"""Incrementally read the existing derived-unit JSON format without a file copy."""
from __future__ import annotations
import json


# A 10-million-character unit remains admissible even if every Unicode code
# point is escaped as a surrogate pair (12 JSON characters), plus metadata.
MAX_UNIT_RECORD_CHARS = 120_065_536


class UnitRecordLimit(ValueError):
    pass


def iter_unit_records(stream, *, max_record_chars=MAX_UNIT_RECORD_CHARS):
    if type(max_record_chars) is not int or max_record_chars < 1:
        raise ValueError('Derived text record bound must be positive')
    decoder = json.JSONDecoder()
    buffer = ''
    ended = False

    def fill():
        nonlocal buffer, ended
        data = stream.read(64 * 1024)
        ended = not data
        buffer += data

    def trim():
        nonlocal buffer
        buffer = buffer.lstrip()
        while not buffer and not ended:
            fill()
            buffer = buffer.lstrip()

    def token(expected):
        nonlocal buffer
        trim()
        if not buffer.startswith(expected):
            raise ValueError('Malformed derived text container')
        buffer = buffer[len(expected):]

    def value():
        nonlocal buffer
        trim()
        while True:
            try:
                result, end = decoder.raw_decode(buffer)
                if end > max_record_chars:
                    raise UnitRecordLimit('Derived text unit record exceeds the bounded reader limit; its inventory remains unresolved.')
                if end == len(buffer) and not ended:
                    fill()
                    continue
                buffer = buffer[end:]
                return result
            except json.JSONDecodeError:
                if len(buffer) > max_record_chars:
                    raise UnitRecordLimit('Derived text unit record exceeds the bounded reader limit; its inventory remains unresolved.')
                if ended:
                    raise ValueError('Malformed derived text value') from None
                fill()

    token('{')
    version = None
    seen = set()
    while True:
        key = value()
        if key not in {'version', 'units'} or key in seen:
            raise ValueError('Unexpected derived text field')
        seen.add(key)
        token(':')
        if key == 'version':
            version = value()
        else:
            token('[')
            trim()
            if buffer.startswith(']'):
                token(']')
            else:
                while True:
                    record = value()
                    if not isinstance(record, dict):
                        raise ValueError('Malformed derived text unit')
                    yield record
                    trim()
                    if buffer.startswith(']'):
                        token(']')
                        break
                    token(',')
        trim()
        if buffer.startswith('}'):
            token('}')
            break
        token(',')
    trim()
    if buffer or seen != {'version', 'units'} or type(version) is not int or version != 1:
        raise ValueError('Invalid derived text container')
