from __future__ import annotations


def render_completion(shell: str) -> str:
    if shell == "bash":
        return _bash_completion()
    if shell == "zsh":
        return _zsh_completion()
    if shell == "fish":
        return _fish_completion()
    raise ValueError(f"Unsupported shell: {shell}")


def _bash_completion() -> str:
    return """_codex_stats_completions()
{
  local cur prev
  cur="${COMP_WORDS[COMP_CWORD]}"
  prev="${COMP_WORDS[COMP_CWORD-1]}"
  local cmds="today week month session models project daily compare history costs insights top export import doctor"
  if [[ "${prev}" == "completions" ]]; then
    COMPREPLY=( $(compgen -W "bash zsh fish" -- "$cur") )
    return 0
  fi
  COMPREPLY=( $(compgen -W "$cmds --json --days --color" -- "$cur") )
}
complete -F _codex_stats_completions codex-stats
"""


def _zsh_completion() -> str:
    return """#compdef codex-stats

_codex_stats() {
  local -a commands
  commands=(
    'today:Show today'
    'week:Show week'
    'month:Show month'
    'session:Show session'
    'models:Show models'
    'project:Show projects'
    'daily:Show daily usage'
    'compare:Compare windows'
    'history:Show history'
    'costs:Show costs'
    'insights:Show insights'
    'top:Show top sessions'
    'export:Export stats'
    'import:Import stats'
    'doctor:Validate local data'
  )
  _arguments '*:command:->cmds'
  case $state in
    cmds) _describe 'command' commands ;;
  esac
}

_codex_stats "$@"
"""


def _fish_completion() -> str:
    commands = [
        "today",
        "week",
        "month",
        "session",
        "models",
        "project",
        "daily",
        "compare",
        "history",
        "costs",
        "insights",
        "top",
        "export",
        "import",
        "doctor",
    ]
    lines = [f"complete -c codex-stats -f -a '{command}'" for command in commands]
    return "\n".join(lines) + "\n"
