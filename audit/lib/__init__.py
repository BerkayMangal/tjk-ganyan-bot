"""audit.lib — read-only data loaders and stat builders for Phase 0 data audit.

Scripts under audit/ must NEVER call live scrapers or model inference.
They read only what was previously recorded by the bot (DB or JSONL).
"""
