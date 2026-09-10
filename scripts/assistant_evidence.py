"""Project-only Git evidence: bounded approved blobs, with safe numeric projection."""

import re

import platform_local as p

FILES = (
    "charts/demo-app/values.yaml",
    "gitops/staging/values.yaml",
    "previewforge-demo/app/config.py",
)


def port_value(path, text):
    if path.endswith(".py"):
        match = re.search(r"^\s*database_port\s*:\s*int\s*=\s*(\d{1,5})\s*$", text, re.MULTILINE)
    else:
        block = re.search(r"^database:\s*\n((?:[ \t]+[^\n]*\n|\n)*)", text + "\n", re.MULTILINE)
        match = re.search(r"^  port:\s*(\d{1,5})\s*$", block[1], re.MULTILINE) if block else None
    return int(match[1]) if match and 1 <= int(match[1]) <= 65535 else None


def configuration_diff(good, bad):
    if not all(re.fullmatch(r"[a-f0-9]{40}", x) for x in (good, bad)):
        raise ValueError("Use exact known-good and observed configuration Git commits")
    result = []
    for path in FILES:
        values = []
        for sha in (good, bad):
            size = int(p.run("git", "-C", p.ROOT, "cat-file", "-s", sha + ":" + path, quiet=True))
            if size > 65536:
                raise ValueError("Approved configuration blob exceeds 64 KiB")
            raw = p.run("git", "-C", p.ROOT, "show", sha + ":" + path, quiet=True)
            values.append(port_value(path, raw))
        if values[0] != values[1] and None not in values:
            result.extend([f"- DATABASE_PORT={values[0]}", f"+ DATABASE_PORT={values[1]}"])
    return "\n".join(dict.fromkeys(result))
