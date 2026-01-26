# Policy Exceptions

This file documents approved exceptions to the "no defaults or fallbacks without explicit exception" policy defined in the global CLAUDE.md.

---

## Exception 1: Model Download Defaults

**Date**: 2026-01-26

**Scope**: Model manager components (`src/model_managers/`)

**Exception**: The model download system may use sensible defaults for:

1. **Default model selection**: When no model is configured, automatically select the smallest/fastest model for the active backend.
2. **Download location**: Use XDG-compliant directories without explicit user configuration:
   - Models: `$XDG_DATA_HOME/speak2type/models/` (default: `~/.local/share/speak2type/models/`)
   - Cache: `$XDG_CACHE_HOME/speak2type/` (default: `~/.cache/speak2type/`)
3. **Model revision pinning**: Use pinned revisions from `models.json` when user doesn't specify a version.

**Rationale**:
- Users expect speech-to-text to "just work" after installation without manual model configuration.
- Following XDG Base Directory Specification is the standard Linux convention.
- Pinned model versions ensure reproducibility and security.

**Explicit behaviors**:
- Model downloads show progress and require user consent on first download.
- All model metadata (id, revision, sha256) is logged and verifiable.
- Users can override all defaults via settings UI or configuration files.

**Tests required**:
- Test default model selection for each backend
- Test XDG directory resolution with and without environment variables set
- Test pinned revision enforcement
