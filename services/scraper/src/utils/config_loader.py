# will read the .yaml files from configs folder and convert them into python dictionaries for the scraper to use

# [FIX] ADDED FUNCTIONALITIES COMMENTS:
# 1. Added validate_config() to catch missing/wrong forum and state values at load time —
#    previously bad configs silently defaulted to CERC mid-pipeline with no error thrown.
# 2. Forum enum membership is checked directly against the known values so config_loader
#    stays independent (no circular import from models.schema).
# 3. Old metadata_static.authority pattern (BEE-style) logs a warning so you know which
#    YAMLs still need migrating, but doesn't hard-crash so old configs still load.
# 4. extras block is passed through as-is — any site-specific keys (pagination, headers,
#    custom wait strategies, etc.) live there and reach the collector without validation.

import yaml
import os
import logging

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Reference tables — kept here so config_loader has no imports
# from models.schema (avoids circular import risk).
# Update these if Forum or state enums change in schema.py.
# ──────────────────────────────────────────────────────────────

# Valid Forum enum member names (the Python keys, not the .value strings)
VALID_FORUMS = {
    "CERC", "APTEL", "SC",
    "HC_DELHI", "HC_BOMBAY",
    "SERC_MH", "SERC_GJ", "SERC_KA", "SERC_RJ", "SERC_TN"
}

# Valid state codes used by generic_collector and DataOrchestrator
VALID_STATES = {
    "CENTRAL",  # All federal forums: CERC, APTEL, SC, HC_DELHI, HC_BOMBAY
    "MH",       # SERC_MH
    "GJ",       # SERC_GJ
    "KA",       # SERC_KA
    "RJ",       # SERC_RJ
    "TN",       # SERC_TN
    "DL",       # Delhi HC matters
}

# Required top-level keys every YAML must have
REQUIRED_KEYS = {"site_name", "forum", "state", "jurisdiction", "base_url", "start_url"}


def validate_config(config: dict, site_name: str) -> None:
    """
    Validates a loaded config dict against required keys and known enum values.
    Raises ValueError with a clear message on the first problem found so the
    pipeline fails loudly at startup rather than silently mid-run.
    """
    # 1. Check all required keys are present
    missing = REQUIRED_KEYS - config.keys()
    if missing:
        raise ValueError(
            f"[{site_name}.yaml] Missing required keys: {sorted(missing)}\n"
            f"Every YAML must have: {sorted(REQUIRED_KEYS)}"
        )

    # 2. Validate forum value against known Forum enum members
    forum_val = str(config.get("forum", "")).upper()
    if forum_val not in VALID_FORUMS:
        raise ValueError(
            f"[{site_name}.yaml] Invalid forum: '{forum_val}'\n"
            f"Must be one of: {sorted(VALID_FORUMS)}"
        )

    # 3. Validate state value against known state codes
    state_val = str(config.get("state", "")).upper()
    if state_val not in VALID_STATES:
        raise ValueError(
            f"[{site_name}.yaml] Invalid state: '{state_val}'\n"
            f"Must be one of: {sorted(VALID_STATES)}"
        )

    # 4. Warn about old metadata_static.authority pattern (BEE-style legacy configs)
    # These still load fine but should be migrated to top-level forum/state keys.
    if "metadata_static" in config and "authority" in config.get("metadata_static", {}):
        logger.warning(
            f"[{site_name}.yaml] 'metadata_static.authority' is deprecated. "
            f"Use top-level 'forum' and 'state' keys instead. Config loaded but should be migrated."
        )


def load_site_config(site_name: str) -> dict:
    """
    Loads and validates a site YAML config. Returns a flat dict the collector can use directly.
    Raises FileNotFoundError if the file doesn't exist, ValueError if validation fails.
    """
    # path to the configs folder, relative to this file
    # Current file: services/scraper/src/utils/config_loader.py
    base_path = os.path.dirname(os.path.abspath(__file__))

    # 1. ../ goes to src
    # 2. ../../ goes to scraper
    # 3. ../../../ - This actually goes to 'services'. 
    # If your 'configs' folder is inside 'scraper', you only need TWO levels up.

    config_path = os.path.join(base_path, "../../configs", f"{site_name}.yaml")

    # Resolve the .. to a clean absolute path
    clean_path = os.path.abspath(config_path)

    if not os.path.exists(clean_path):
        raise FileNotFoundError(f"Config not found for: {site_name} at {clean_path}")

    with open(clean_path, 'r') as f:
        config = yaml.safe_load(f)

    # Normalize forum and state to uppercase in-place so the rest of the
    # pipeline never has to worry about casing from the YAML.
    if "forum" in config:
        config["forum"] = str(config["forum"]).upper()
    if "state" in config:
        config["state"] = str(config["state"]).upper()

    # Validate before returning — fail loud and early
    validate_config(config, site_name)

    return config