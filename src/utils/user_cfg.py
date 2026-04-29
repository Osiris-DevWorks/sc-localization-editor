"""Manages Star Citizen user.cfg file for language and other settings."""
import logging
from pathlib import Path

from src.utils.settings import AppSettings

logger = logging.getLogger(__name__)


def ensure_user_cfg_language() -> bool:
    """Ensure Star Citizen's user.cfg has g_language = english setting.

    Writes to the **active channel's** ``user.cfg`` — whichever of
    LIVE/PTU/EPTU/HOTFIX/TECH-PREVIEW is currently selected. Creates the
    file if absent, or adds the language line if present but missing the
    setting, leaving other settings untouched.

    Returns:
        True if successful, False if the channel's install dir isn't
        accessible (channel not installed, path misconfigured, etc.).
    """
    channel_path = AppSettings.get_game_install_path()
    if not channel_path:
        logger.warning("Game install path not configured — skipping user.cfg setup")
        return False

    channel_dir = Path(channel_path)
    if not channel_dir.exists():
        logger.warning(
            f"{AppSettings.get_active_channel()} directory not found at {channel_dir} "
            f"— skipping user.cfg setup"
        )
        return False

    user_cfg_path = channel_dir / "user.cfg"

    # Language setting we want to ensure
    language_line = "g_language = english"

    try:
        if user_cfg_path.exists():
            # File exists — check if language setting is present
            content = user_cfg_path.read_text(encoding="utf-8")
            lines = content.splitlines()

            # Check if language setting already exists
            has_language = any(line.strip() == language_line for line in lines)

            if not has_language:
                # Add language setting if missing
                logger.info(f"Adding language setting to {user_cfg_path}")
                if lines and lines[-1].strip():  # Ensure file ends with newline
                    lines.append("")
                lines.append(language_line)
                user_cfg_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                logger.info(f"Added '{language_line}' to user.cfg")
            else:
                logger.info("user.cfg already has language setting")
        else:
            # File doesn't exist — create it with language setting
            logger.info(f"Creating user.cfg at {user_cfg_path}")
            user_cfg_path.write_text(language_line + "\n", encoding="utf-8")
            logger.info(f"Created user.cfg with '{language_line}'")

        return True
    except Exception as e:
        logger.exception(f"Failed to manage user.cfg at {user_cfg_path}: {e}")
        return False
