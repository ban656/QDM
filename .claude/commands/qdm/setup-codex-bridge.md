---
description: Install and verify the official codex-plugin-cc bridge for this project.
argument-hint: "[optional note]"
---

# QDM Codex Bridge Setup

You are configuring Claude Code to work with this project's QDM/Codex bridge.

Explain and, when the environment permits, guide the user through:

```text
/plugin marketplace add openai/codex-plugin-cc
/plugin install codex@openai-codex
/reload-plugins
/codex:setup
/codex:status
```

Then verify whether these commands are available:

```text
/codex:review
/codex:adversarial-review
/codex:rescue
/codex:transfer
```

If the plugin is not available, do not block the modeling workflow.  Tell the
user that `/qdm:*` commands will write Codex request files under role-specific
auto workspace paths:

```text
<auto_workspace>/codex_workspace/questioner/requests/
<auto_workspace>/codex_workspace/evolver/requests/
```

Project note:

$ARGUMENTS
