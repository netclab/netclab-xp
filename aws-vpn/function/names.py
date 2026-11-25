"""configuration-iosxe's names: an object of a section `name` on Device `device` is called
`<device>--<slug>--<8 hex>`, at most 63 characters, or it composes nothing."""

import hashlib
import re


def xr_name(device: str, name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    slug = slug[: max(0, 51 - len(device))].removesuffix("-")
    return f"{device}--{slug}--{hashlib.sha256(name.encode()).hexdigest()[:8]}"
