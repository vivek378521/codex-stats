"""Cross-CLI tool taxonomy.

Every coding agent names its tools differently: Claude Code says ``Bash`` and ``Read``,
Codex says ``exec_command`` and ``apply_patch``, OpenCode says ``bash`` and ``edit``. This
module collapses those names into a small set of shared categories so the Overview tab can
aggregate behavior across tools instead of showing five incompatible vocabularies.

Category matching is exact-first against a table of names actually observed in the wild,
then falls back to ordered substring rules for anything unrecognized. Substring rules are
deliberately conservative: a tool that cannot be placed confidently lands in ``other``
rather than being misfiled into a category that would distort the read/write ratio.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex

from .models import (
    TOOL_CATEGORY_AGENT,
    TOOL_CATEGORY_EDIT,
    TOOL_CATEGORY_EXEC,
    TOOL_CATEGORY_OTHER,
    TOOL_CATEGORY_PLAN,
    TOOL_CATEGORY_READ,
    TOOL_CATEGORY_SEARCH,
    TOOL_CATEGORY_WEB,
    TOOL_STATUS_COMPLETED,
    ToolCall,
)

# Exact matches on the normalized name. Keys are already normalized (lowercase, alnum only).
_EXACT_CATEGORIES: dict[str, str] = {
    # read
    "read": TOOL_CATEGORY_READ,
    "readfile": TOOL_CATEGORY_READ,
    "readfiles": TOOL_CATEGORY_READ,
    "view": TOOL_CATEGORY_READ,
    "viewfile": TOOL_CATEGORY_READ,
    "cat": TOOL_CATEGORY_READ,
    "open": TOOL_CATEGORY_READ,
    "openfile": TOOL_CATEGORY_READ,
    "getfile": TOOL_CATEGORY_READ,
    "notebookread": TOOL_CATEGORY_READ,
    # edit
    "edit": TOOL_CATEGORY_EDIT,
    "editfile": TOOL_CATEGORY_EDIT,
    "editfilecontent": TOOL_CATEGORY_EDIT,
    "write": TOOL_CATEGORY_EDIT,
    "writefile": TOOL_CATEGORY_EDIT,
    "writetofile": TOOL_CATEGORY_EDIT,
    "createfile": TOOL_CATEGORY_EDIT,
    "updatefile": TOOL_CATEGORY_EDIT,
    "deletefile": TOOL_CATEGORY_EDIT,
    "movefile": TOOL_CATEGORY_EDIT,
    "copyfile": TOOL_CATEGORY_EDIT,
    "multiedit": TOOL_CATEGORY_EDIT,
    "multieditfile": TOOL_CATEGORY_EDIT,
    "applypatch": TOOL_CATEGORY_EDIT,
    "patch": TOOL_CATEGORY_EDIT,
    "patchfile": TOOL_CATEGORY_EDIT,
    "strreplaceeditor": TOOL_CATEGORY_EDIT,
    "strreplace": TOOL_CATEGORY_EDIT,
    "notebookedit": TOOL_CATEGORY_EDIT,
    "insert": TOOL_CATEGORY_EDIT,
    "replace": TOOL_CATEGORY_EDIT,
    # exec
    "exec": TOOL_CATEGORY_EXEC,
    "execcommand": TOOL_CATEGORY_EXEC,
    "bash": TOOL_CATEGORY_EXEC,
    "pwsh": TOOL_CATEGORY_EXEC,
    "sh": TOOL_CATEGORY_EXEC,
    "shell": TOOL_CATEGORY_EXEC,
    "run": TOOL_CATEGORY_EXEC,
    "runcommand": TOOL_CATEGORY_EXEC,
    "runterminalcmd": TOOL_CATEGORY_EXEC,
    "terminal": TOOL_CATEGORY_EXEC,
    "terminalopen": TOOL_CATEGORY_EXEC,
    "terminalsend": TOOL_CATEGORY_EXEC,
    "terminalread": TOOL_CATEGORY_EXEC,
    "terminallist": TOOL_CATEGORY_EXEC,
    "terminalclose": TOOL_CATEGORY_EXEC,
    "terminalsignal": TOOL_CATEGORY_EXEC,
    "joblist": TOOL_CATEGORY_EXEC,
    "joboutput": TOOL_CATEGORY_EXEC,
    "jobkill": TOOL_CATEGORY_EXEC,
    "writestdin": TOOL_CATEGORY_EXEC,
    "wait": TOOL_CATEGORY_EXEC,
    # search
    "grep": TOOL_CATEGORY_SEARCH,
    "glob": TOOL_CATEGORY_SEARCH,
    "ls": TOOL_CATEGORY_SEARCH,
    "list": TOOL_CATEGORY_SEARCH,
    "find": TOOL_CATEGORY_SEARCH,
    "search": TOOL_CATEGORY_SEARCH,
    "searchfiles": TOOL_CATEGORY_SEARCH,
    "filesearch": TOOL_CATEGORY_SEARCH,
    "codebasesearch": TOOL_CATEGORY_SEARCH,
    "ripgrep": TOOL_CATEGORY_SEARCH,
    "locate": TOOL_CATEGORY_SEARCH,
    # web
    "websearch": TOOL_CATEGORY_WEB,
    "webfetch": TOOL_CATEGORY_WEB,
    "fetch": TOOL_CATEGORY_WEB,
    "browser": TOOL_CATEGORY_WEB,
    "web": TOOL_CATEGORY_WEB,
    "http": TOOL_CATEGORY_WEB,
    "crawl": TOOL_CATEGORY_WEB,
    # agent
    "task": TOOL_CATEGORY_AGENT,
    "agent": TOOL_CATEGORY_AGENT,
    "subagent": TOOL_CATEGORY_AGENT,
    "dispatchagent": TOOL_CATEGORY_AGENT,
    "sendmessage": TOOL_CATEGORY_AGENT,
    "interruptagent": TOOL_CATEGORY_AGENT,
    "listagents": TOOL_CATEGORY_AGENT,
    "listsubagentmodels": TOOL_CATEGORY_AGENT,
    # plan
    "plan": TOOL_CATEGORY_PLAN,
    "todowrite": TOOL_CATEGORY_PLAN,
    "todoread": TOOL_CATEGORY_PLAN,
    "taskcreate": TOOL_CATEGORY_PLAN,
    "taskupdate": TOOL_CATEGORY_PLAN,
    "tasklist": TOOL_CATEGORY_PLAN,
    "updateplan": TOOL_CATEGORY_PLAN,
    "enterplanmode": TOOL_CATEGORY_PLAN,
    "exitplanmode": TOOL_CATEGORY_PLAN,
    "creategoal": TOOL_CATEGORY_PLAN,
    "getgoal": TOOL_CATEGORY_PLAN,
    "updategoal": TOOL_CATEGORY_PLAN,
}

# Names that must never be caught by a substring rule even though they look like one.
# "thread" contains "read", which would otherwise misfile thread tools as file reads.
_NEVER_READ = ("thread", "already", "spread", "ready", "readmeonly")

_ARG_KEYS = (
    "command",
    "cmd",
    "script",
    "shell_command",
    "query",
    "pattern",
    "file_path",
    "filepath",
    "filePath",
    "path",
    "file",
    "notebook_path",
    "url",
    "prompt",
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_WHITESPACE = re.compile(r"\s+")

_FINGERPRINT_MAX = 400

_COMMAND_KEYS = ("command", "cmd", "script", "shell_command")
_FILE_KEYS = ("file_path", "filepath", "filePath", "path", "file", "notebook_path", "notebookPath")
_SKILL_TOOL_NAMES = {"skill", "activateskill", "loadskill", "useskill"}
_SUBAGENT_TYPE_KEYS = ("subagent_type", "agent_type", "type")
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SEGMENT_RE = re.compile(r"&&|\|\||[;|]")
_QUOTED_RE = re.compile(r"""(['"])(?:\\.|(?!\1).)*\1""")
_VERIFY_RE = re.compile(
    r"(?:"
    r"(?:pytest|py\.test|tox|nox|vitest|jest|mypy|ruff|flake8|pylint|tsc|eslint|biome)"
    r"|(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:test|build|lint|check|typecheck)"
    r"|cargo\s+(?:test|clippy|check)"
    r"|go\s+(?:test|vet)"
    r"|make\s+(?:test|check)"
    r"|just\s+test"
    r"|python(?:3)?\s+-m\s+(?:pytest|unittest|mypy)"
    r")\b"
)
_PREFIX_LAUNCHERS = {"sudo", "env", "command", "time", "nohup", "exec"}
_EXEC_LAUNCHERS = {"npx", "bunx", "pnpx"}
_RUN_LAUNCHERS = {"uv", "poetry", "pipenv", "pdm", "hatch", "rye", "bundle"}
_PYTHON_NAMES = {"python", "python3", "py"}
_SHELL_READ_VERBS = {"cat", "bat", "head", "tail", "sed", "less", "more", "wc", "nl", "jq"}
_PATCH_FILE_RE = re.compile(
    r"^\*\*\* (?:(?:Add|Update|Delete) File|Move to):\s*(.+?)\s*$",
    re.MULTILINE,
)


def _arguments_dict(arguments: object) -> dict:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str) and arguments.strip().startswith(("{", "[")):
        try:
            parsed = json.loads(arguments)
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _argument_text(arguments: object) -> str:
    if isinstance(arguments, str):
        return arguments
    return ""


def _command_text(arguments: object) -> str | None:
    args = _arguments_dict(arguments)
    for key in _COMMAND_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value
    if not args:
        text = _argument_text(arguments).strip()
        if text and not text.startswith(("{", "[", "*** Begin Patch", "*** Add File", "*** Update File")):
            return text
    return None


def _command_words(segment: str) -> list[str]:
    try:
        words = shlex.split(segment)
    except ValueError:
        words = segment.split()
    while words:
        head = os.path.basename(words[0].strip("\"'"))
        if _ENV_ASSIGN_RE.fullmatch(words[0]):
            words = words[1:]
            continue
        if head in _PREFIX_LAUNCHERS:
            words = words[1:]
            while words and words[0].startswith("-"):
                words = words[1:]
            continue
        if head in _EXEC_LAUNCHERS:
            words = words[1:]
            while words and words[0].startswith("-"):
                words = words[1:]
            continue
        if head in _RUN_LAUNCHERS and len(words) > 1 and words[1] in ("run", "exec"):
            words = words[2:]
            while words and words[0].startswith("-"):
                words = words[1:]
            continue
        if head in _PYTHON_NAMES and len(words) > 1 and words[1] == "-m":
            words = words[2:]
            continue
        break
    return words


def _command_segments(command: str) -> list[list[str]]:
    cleaned = _QUOTED_RE.sub(" ", command)
    return [_command_words(segment) for segment in _SEGMENT_RE.split(cleaned)]


def command_verb(command: str | None) -> str | None:
    if not command:
        return None
    for words in _command_segments(command):
        if words:
            return os.path.basename(words[0].strip("\"'"))
    return None


def is_verification_command(command: str | None) -> bool:
    if not command:
        return False
    for words in _command_segments(command):
        if not words:
            continue
        text = " ".join([os.path.basename(words[0]), *words[1:]])
        if _VERIFY_RE.match(text):
            return True
    return False


def is_pr_create_command(command: str | None) -> bool:
    if not command:
        return False
    for words in _command_segments(command):
        if len(words) < 3:
            continue
        verb = os.path.basename(words[0]).lower()
        if verb in ("gh", "glab") and words[1] in ("pr", "mr") and words[2] == "create":
            return True
    return False


def mcp_server_from_name(raw_name: object) -> str | None:
    if not isinstance(raw_name, str):
        return None
    parts = [part for part in raw_name.strip().split("__") if part]
    if len(parts) >= 3 and parts[0].lower() == "mcp":
        return parts[1]
    return None


def _skill_from_arguments(arguments: object) -> str | None:
    args = _arguments_dict(arguments)
    for key in ("skill", "command", "name"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lstrip("/")
    return None


def _subagent_type_from_arguments(arguments: object) -> str | None:
    args = _arguments_dict(arguments)
    for key in _SUBAGENT_TYPE_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "general"


def _shell_read_path(command: str | None) -> str | None:
    if not command:
        return None
    for words in _command_segments(command):
        if not words:
            continue
        verb = os.path.basename(words[0])
        if verb not in _SHELL_READ_VERBS:
            continue
        candidates = [word for word in words[1:] if not word.startswith("-")]
        if candidates:
            return candidates[-1].strip("\"'")
    return None


def file_path_from_call(raw_name: object, arguments: object, category: str) -> str | None:
    args = _arguments_dict(arguments)
    for key in _FILE_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    text = _argument_text(arguments)
    if category == TOOL_CATEGORY_EDIT and text:
        match = _PATCH_FILE_RE.search(text)
        if match:
            return match.group(1).strip()
    if category in (TOOL_CATEGORY_READ, TOOL_CATEGORY_EXEC):
        return _shell_read_path(_command_text(arguments))
    return None


def normalize_tool_name(raw: object) -> str:
    """Reduce a tool name to a comparable stem.

    Strips an ``mcp__server__`` prefix so MCP tools match their base name, then keeps only
    lowercase alphanumerics, so ``MultiEdit``, ``multi_edit`` and ``multiedit`` collapse.
    """
    if not isinstance(raw, str):
        return ""
    name = raw.strip()
    if not name:
        return ""
    if name.lower().startswith("mcp__"):
        segments = [part for part in name.split("__") if part]
        if segments:
            name = segments[-1]
    return _NON_ALNUM.sub("", name.lower())


def tool_category(raw: object) -> str:
    """Map a raw tool name onto a shared category."""
    name = normalize_tool_name(raw)
    if not name:
        return TOOL_CATEGORY_OTHER

    exact = _EXACT_CATEGORIES.get(name)
    if exact is not None:
        return exact

    if any(token in name for token in _NEVER_READ):
        return TOOL_CATEGORY_OTHER

    # Polling and continuation tools are exec, and must be tested before the "write" rule
    # so write_stdin is not filed as a file edit.
    if name in ("writestdin", "wait", "poll", "readinput", "continue"):
        return TOOL_CATEGORY_EXEC

    if "patch" in name:
        return TOOL_CATEGORY_EDIT
    if "write" in name or "edit" in name or "delete" in name or "insert" in name:
        return TOOL_CATEGORY_EDIT
    if any(token in name for token in ("grep", "glob", "search", "find", "locate")):
        return TOOL_CATEGORY_SEARCH
    if any(token in name for token in ("fetch", "web", "browser", "http", "crawl", "url")):
        return TOOL_CATEGORY_WEB
    if "agent" in name:
        return TOOL_CATEGORY_AGENT
    if name.startswith("task") or any(token in name for token in ("plan", "todo")):
        return TOOL_CATEGORY_PLAN
    if any(token in name for token in ("read", "view", "cat")):
        return TOOL_CATEGORY_READ
    if any(token in name for token in ("exec", "bash", "shell", "terminal", "command", "run")):
        return TOOL_CATEGORY_EXEC
    return TOOL_CATEGORY_OTHER


def _identity_argument(arguments: object) -> str:
    """Reduce tool arguments to the part that identifies *what work* the call did.

    Two calls that differ only in bookkeeping fields, such as a description or a timeout,
    are still the same call for repeat-detection purposes. Argument strings are parsed as
    JSON first so key picking applies to sources (Codex) that pass a serialized blob.
    """
    if isinstance(arguments, str) and arguments.strip():
        try:
            parsed_args = json.loads(arguments)
        except json.JSONDecodeError:
            parsed_args = None
        if isinstance(parsed_args, dict):
            arguments = parsed_args
        elif isinstance(parsed_args, list):
            arguments = json.dumps(parsed_args, sort_keys=True, default=str)
    if isinstance(arguments, dict):
        parts: list[str] = []
        for key in _ARG_KEYS:
            value = arguments.get(key)
            if isinstance(value, (str, int, float)) and str(value).strip():
                parts.append(f"{key}={value}")
        if not parts:
            try:
                return _WHITESPACE.sub(" ", json.dumps(arguments, sort_keys=True, default=str)).strip()[:_FINGERPRINT_MAX]
            except (TypeError, ValueError):
                return _WHITESPACE.sub(" ", str(arguments)).strip()[:_FINGERPRINT_MAX]
        text = " ".join(parts)
    elif arguments is None:
        return ""
    else:
        text = str(arguments)
    return _WHITESPACE.sub(" ", text).strip()[:_FINGERPRINT_MAX]


def tool_fingerprint(raw_name: object, arguments: object) -> str:
    """Stable identity for a call, used to count repeated work inside a session."""
    digest = hashlib.sha1()
    digest.update(normalize_tool_name(raw_name).encode("utf-8"))
    digest.update(b"\x00")
    digest.update(_identity_argument(arguments).encode("utf-8"))
    return digest.hexdigest()


def make_tool_call(
    raw_name: object,
    arguments: object = None,
    *,
    status: str = TOOL_STATUS_COMPLETED,
    duration_ms: int | None = None,
) -> ToolCall:
    category = tool_category(raw_name)
    command = _command_text(arguments) if category == TOOL_CATEGORY_EXEC else None
    normalized = normalize_tool_name(raw_name)
    return ToolCall(
        name=str(raw_name) if isinstance(raw_name, str) else "unknown",
        category=category,
        fingerprint=tool_fingerprint(raw_name, arguments),
        status=status,
        duration_ms=duration_ms,
        verb=command_verb(command),
        is_verification=is_verification_command(command),
        is_pr_create=is_pr_create_command(command),
        mcp_server=mcp_server_from_name(raw_name),
        skill=_skill_from_arguments(arguments) if normalized in _SKILL_TOOL_NAMES else None,
        subagent_type=_subagent_type_from_arguments(arguments) if category == TOOL_CATEGORY_AGENT else None,
        file_path=file_path_from_call(raw_name, arguments, category),
    )


def output_looks_failed(output: object) -> bool:
    """Conservative failure detection for sources with no explicit per-call status.

    Codex rollouts store a tool result as free text that frequently contains source code,
    log output, and file contents, so scanning the body for words like "error" or
    "invalid" produces false positives at a high rate. Only the structured header of a
    result is trusted, which under-reports rather than over-reports: a Codex error rate
    from this detector is a lower bound.

    Sources that record status directly, such as OpenCode and Claude Code, do not use this.
    """
    text = coalesce_output_text(output)
    if not text:
        return False
    header = text[:300].lstrip().lower()
    if header.startswith(_FAILED_PREFIXES):
        return True
    match = _EXIT_CODE_RE.search(text[:400])
    return bool(match and match.group(1) != "0")


# Headers and tool-emitted failure banners that only ever appear at the start of a result.
_FAILED_PREFIXES = (
    "script failed",
    "apply_patch verification failed",
    "applypatch verification failed",
    "verification failed",
)

_EXIT_CODE_RE = re.compile(r"Exit code:\s*(-?\d+)")


def coalesce_output_text(output: object) -> str:
    """Flatten the several shapes a tool result can take into plain text."""
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        chunks: list[str] = []
        for block in output:
            if isinstance(block, str):
                chunks.append(block)
            elif isinstance(block, dict):
                for key in ("text", "content", "output"):
                    value = block.get(key)
                    if isinstance(value, str):
                        chunks.append(value)
                    elif isinstance(value, list):
                        chunks.extend(item for item in value if isinstance(item, str))
        return "\n".join(chunks)
    if isinstance(output, dict):
        for key in ("text", "content", "output", "stdout", "result"):
            value = output.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, (list, dict)):
                nested = coalesce_output_text(value)
                if nested:
                    return nested
        try:
            return json.dumps(output, default=str)
        except (TypeError, ValueError):
            return str(output)
    return ""


__all__ = [
    "coalesce_output_text",
    "command_verb",
    "file_path_from_call",
    "is_pr_create_command",
    "is_verification_command",
    "make_tool_call",
    "mcp_server_from_name",
    "normalize_tool_name",
    "output_looks_failed",
    "tool_category",
    "tool_fingerprint",
]
