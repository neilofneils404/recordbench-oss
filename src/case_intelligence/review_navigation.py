"""Matter-local return navigation for source and saved-review workflows."""
from urllib.parse import unquote, urlsplit


def matter_return_path(slug, value, *, fallback=''):
    if not isinstance(value, str) or len(value) > 4000:
        return fallback
    try:
        parsed = urlsplit(value)
    except ValueError:
        return fallback
    prefix = f'/matters/{slug}'
    if (parsed.scheme or parsed.netloc or '\\' in value
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        return fallback
    path = parsed.path
    # A browser normalizes literal and encoded dot segments before navigation.
    # Also reject nested encodings rather than accepting a path a later decoder
    # could turn into a different matter or a backslash-separated URL.
    for _ in range(4):
        decoded = unquote(path)
        if (not (decoded == prefix or decoded.startswith(prefix + '/'))
                or any(part in ('.', '..') for part in decoded.split('/'))
                or '\\' in decoded or any(ord(c) < 32 or ord(c) == 127 for c in decoded)):
            return fallback
        if decoded == path:
            return value
        path = decoded
    return fallback
