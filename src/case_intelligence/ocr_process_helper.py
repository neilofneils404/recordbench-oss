"""Apply an OCR output-file limit in a fresh process, then replace it with OCR.

Applying limits here keeps the threaded application out of ``preexec_fn`` and
leaves its own process limits unchanged. Exec preserves the parent's timeout
and kill target; it does not leave a second, unsupervised recognition child.
"""
from __future__ import annotations

import os
import resource
import signal
import sys

MAX_OUTPUT_BYTES = 16 * 1024 * 1024


def main(arguments: list[str]) -> int:
    try:
        maximum = int(arguments[0])
        command = arguments[1:]
        if not 0 < maximum <= MAX_OUTPUT_BYTES or not command or not os.path.isabs(command[0]):
            return 125
        soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
        effective = min(value for value in (maximum, soft, hard) if value != resource.RLIM_INFINITY)
        resource.setrlimit(resource.RLIMIT_FSIZE, (effective, effective))
        # Python ignores this signal at startup. The exec'd program must instead
        # terminate when it tries to write beyond the enforced file-size cap.
        signal.signal(signal.SIGXFSZ, signal.SIG_DFL)
        os.execv(command[0], command)
    except (IndexError, OSError, ValueError):
        # No unbounded fallback if the operating system cannot apply the limit.
        return 125
    return 125


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
