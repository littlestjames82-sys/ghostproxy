"""Adapter over GhostSlice: slicing + secret scan.

GhostProxy is a runtime for GhostSlice, not a second slicer. All real
slicing and secret detection is delegated to the ``ghostslice`` package
when importable (see tokens._load_ghostslice). When GhostSlice is not
available, slicing reports unavailable and the caller passes content
through untouched (fail-open), which is the plan's stated behaviour.
The secret fallback is a narrow shape check used only when GhostSlice
is absent, and it returns path/line/type only -- never a value.
"""
from __future__ import annotations

import posixpath
import re

from . import tokens as _tokens_mod  # ensures the sibling-path bootstrap ran

_EXTENSION_LANGUAGE = {
    ".py": "python", ".ipynb": "notebook",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".jsx": "javascript",
    ".go": "go", ".rs": "rust", ".java": "java", ".cs": "csharp",
    ".php": "php", ".rb": "ruby", ".kt": "kotlin", ".swift": "swift",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp",
    ".scala": "scala", ".md": "markdown", ".json": "json",
    ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
}


def language_for(path: str) -> str:
    if _tokens_mod.ghostslice_available():
        try:
            from ghostslice.slicer import language_for as gs_language_for
            return gs_language_for(path)
        except Exception:
            pass
    ext = posixpath.splitext(path or "")[1].lower()
    return _EXTENSION_LANGUAGE.get(ext, "text")


def available() -> bool:
    return _tokens_mod.ghostslice_available()


def slice_text(path: str, source: str, mode: str) -> str | None:
    """Slice *source* to *mode* via GhostSlice; None if unavailable/fails."""
    if not available():
        return None
    try:
        from ghostslice.slicer import slice_source
        return slice_source(source, language_for(path), mode, path=path)
    except Exception:
        return None


# Narrow fallback shapes (used ONLY when GhostSlice is absent). Values are
# matched then discarded; only the finding type is ever returned.
#
# Parity policy (seam fix, Oct 14 2026; full audit in SEAM_FIX_REPORT.md):
# these shapes mirror GhostSlice's canonical guard
# (ghostslice/secrets_scan.py, _KNOWN_PATTERNS) so the Slice-absent path
# does not silently catch less than the delegated path for every shape it
# carries. Two canonical behaviours are deliberately NOT mirrored:
# high-entropy-assignment (per-line entropy scoring is Slice's job; the
# fallback stays a pure shape net, which also keeps the fail-open hot
# path free of scoring work) and Slice's full placeholder heuristics
# (the fallback keeps only the marker/repetition checks in
# _looks_placeholder). sensitive-assignment keeps a narrower name gate
# than Slice's on purpose; see the report.
_FALLBACK_SECRET_PATTERNS = (
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("openai-or-anthropic-key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{16,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b")),
    ("password-in-url", re.compile(r"://[^/\s:@'\"]+:[^/\s:@'\"]{3,}@")),
    ("sensitive-assignment", re.compile(
        r"(?i)\b(?:api[_-]?key|secret|password|passwd|token)\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']")),
)

# Slice gates its bare-40-char "aws-secret-key" shape behind an
# AWS-secret context on the same line; the fallback applies the same
# gate, plus the placeholder check below.
_FALLBACK_AWS_SECRET_CONTEXT = re.compile(
    r"aws.{0,20}secret|secret.{0,20}aws", re.IGNORECASE)
_FALLBACK_BARE_40 = re.compile(r"\b[A-Za-z0-9/+=]{40}\b")

# Trimmed copy of Slice's PLACEHOLDER_MARKERS: enough to keep obvious
# documentation examples (AWS's own docs carry a 40-char example key)
# from tripping the bare-40 shape on the fallback path.
_FALLBACK_PLACEHOLDER_MARKERS = (
    "example", "xxx", "your-", "your_", "yourkey", "placeholder",
    "changeme", "change-me", "change_me", "dummy", "sample", "fixture",
    "redacted", "insert-", "insert_", "todo", "fake", "test-key",
    "test_key", "not-a-real", "not_real", "mock",
)


def _looks_placeholder(value: str) -> bool:
    v = (value or "").strip().strip("\"'")
    if not v:
        return True
    low = v.lower()
    if any(m in low for m in _FALLBACK_PLACEHOLDER_MARKERS):
        return True
    if set(v) <= {"*", "x", "X", ".", "-", "_"}:
        return True
    if len(v) >= 6 and len(set(v)) <= 2:
        return True  # repeated short pattern, e.g. abcabcabc or 11111111
    return False


def scan_secrets(path: str, text: str) -> list[dict]:
    """Secret findings for one text: [{path, line, type}] and nothing else.

    The flagged VALUE is never included anywhere in the return value.
    """
    if available():
        try:
            from ghostslice.secrets_scan import scan_text
            return [{"path": f.get("path", path), "line": f.get("line", 0),
                     "type": f.get("type", "unknown")}
                    for f in scan_text(path, text)]
        except Exception:
            pass
    findings = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for ptype, pat in _FALLBACK_SECRET_PATTERNS:
            if pat.search(line):
                findings.append({"path": path, "line": line_no, "type": ptype})
        if _FALLBACK_AWS_SECRET_CONTEXT.search(line):
            m = _FALLBACK_BARE_40.search(line)
            if m and not _looks_placeholder(m.group(0)):
                findings.append({"path": path, "line": line_no,
                                 "type": "aws-secret-key"})
    return findings
