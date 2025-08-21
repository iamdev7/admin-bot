from __future__ import annotations

import re
from datetime import timedelta


_DUR_RE = re.compile(r"^(?P<num>\d+)(?P<unit>[smhd])$", re.IGNORECASE)


def parse_duration(spec: str | None) -> timedelta | None:
    if not spec:
        return None
    s = spec.strip().lower()
    if s in {"perm", "permanent", "forever"}:
        return None
    m = _DUR_RE.match(s)
    if not m:
        raise ValueError("Invalid duration. Use 30s, 10m, 2h, 3d, or perm")
    num = int(m.group("num"))
    unit = m.group("unit")
    if unit == "s":
        return timedelta(seconds=num)
    if unit == "m":
        return timedelta(minutes=num)
    if unit == "h":
        return timedelta(hours=num)
    if unit == "d":
        return timedelta(days=num)
    raise ValueError("Invalid duration unit")

