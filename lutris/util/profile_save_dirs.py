"""Isolate, per profile, save folders or files that live outside the Windows user folder.

Some games save next to their executable, in C:\\ProgramData or in a launcher's
folder; native games and emulators save in the Linux home. The paths listed in
the 'profile_save_dirs' option of a game are turned into symlinks to a copy owned
by the active profile (see lutris.util.profile_links):

    ~/.local/share/lutris/profiles/<profile>/save-dirs/<path key>/<name>

The original content is kept next to it, as <path>.lutris-profile-template.
"""

import hashlib
import os
from typing import Any

from lutris import settings
from lutris.util.log import logger
from lutris.util.profile_links import link_to_profile
from lutris.util.yaml import read_yaml_from_file, write_yaml_to_file

OPTION_NAME = "profile_save_dirs"
TEMPLATE_SUFFIX = ".lutris-profile-template"


def get_state_path() -> str:
    """File remembering which profile each isolated path was last linked to."""
    return os.path.join(settings.PROFILES_DIR, "save-dirs.yml")


def parse_save_dirs(value: str | None) -> list[str]:
    """Paths are separated by ';' or new lines."""
    if not value:
        return []
    return [path.strip() for path in value.replace("\n", ";").split(";") if path.strip()]


def expand_save_dir(path: str, game_dir: str | None, prefix_path: str | None) -> str | None:
    """Resolve $GAMEDIR, $PREFIX and ~; relative paths are relative to the game folder."""
    if "$GAMEDIR" in path:
        if not game_dir:
            return None
        path = path.replace("$GAMEDIR", game_dir)
    if "$PREFIX" in path:
        if not prefix_path:
            return None
        path = path.replace("$PREFIX", prefix_path)
    path = os.path.expanduser(os.path.expandvars(path))
    if not os.path.isabs(path):
        if not game_dir:
            return None
        path = os.path.join(game_dir, path)
    return os.path.normpath(path)


def get_path_key(path: str) -> str:
    digest = hashlib.sha1(path.encode("utf-8")).hexdigest()[:8]
    return "%s-%s" % (os.path.basename(path) or "root", digest)


def get_profile_save_path(path: str, profile_id: str) -> str:
    return os.path.join(settings.PROFILES_DIR, profile_id, "save-dirs", get_path_key(path), os.path.basename(path))


def _is_same_or_inside(path: str, parent: str) -> bool:
    return path == parent or path.startswith(parent.rstrip(os.sep) + os.sep)


def check_save_dir(path: str, protected_paths: list[str]) -> str | None:
    """Return why a path can't be isolated, or None if it can.

    Isolating a folder moves it away; refuse anything that holds the game itself,
    a prefix, Lutris' own data or a whole home folder."""
    if path == os.sep or path == os.path.expanduser("~"):
        return "it is a whole home or root folder"
    for protected in protected_paths:
        if protected and _is_same_or_inside(protected, path):
            return "it contains %s" % protected
    real_path = os.path.join(os.path.realpath(os.path.dirname(path)), os.path.basename(path))
    if _is_same_or_inside(real_path, os.path.abspath(settings.PROFILES_DIR)):
        return "it is already private to a profile"
    return None


def _get_protected_paths(game: Any, prefix_path: str | None) -> list[str]:
    protected = [
        settings.CONFIG_DIR,
        settings.DATA_DIR,
        settings.CACHE_DIR,
        settings.RUNNER_DIR,
        settings.PROFILES_DIR,
        game.directory,
    ]
    if prefix_path:
        protected += [prefix_path, os.path.join(prefix_path, "drive_c")]
    game_config = game.config.game_config if game.config else {}
    for key in ("exe", "main_file"):
        value = game_config.get(key)
        if value:
            protected.append(value if os.path.isabs(value) else os.path.join(game.directory or "", value))
    return [os.path.normpath(os.path.expanduser(path)) for path in protected if path]


def link_game_save_dirs(game: Any, profile_id: str) -> None:
    """Point the extra save paths configured for a game to the active profile's copies."""
    save_dirs = parse_save_dirs(game.runner.system_config.get(OPTION_NAME))
    if not save_dirs:
        return
    prefix_path = getattr(game.runner, "prefix_path", None)
    protected_paths = _get_protected_paths(game, prefix_path)
    state_path = get_state_path()
    state = read_yaml_from_file(state_path) if os.path.exists(state_path) else {}

    for save_dir in save_dirs:
        path = expand_save_dir(save_dir, game.directory, prefix_path)
        if not path:
            logger.warning("Can't resolve save path %s for %s", save_dir, game)
            continue
        reason = check_save_dir(path, protected_paths)
        if reason:
            logger.warning("Not isolating %s per profile: %s", path, reason)
            continue
        profile_path = get_profile_save_path(path, profile_id)
        template_path = path + TEMPLATE_SUFFIX
        exists = any(os.path.lexists(p) for p in (path, template_path, profile_path))
        if not exists and os.path.splitext(path)[1]:
            # Looks like a file that doesn't exist yet; a folder would be created instead
            logger.info("%s doesn't exist yet, it will be isolated once created", path)
            continue

        previous_profile = state.get(path)
        previous_profile_path = get_profile_save_path(path, previous_profile) if previous_profile else None
        try:
            link_to_profile(path, template_path, profile_path, previous_profile_path)
        except Exception as ex:
            logger.exception("Failed to isolate %s for profile %s: %s", path, profile_id, ex)
            continue
        state[path] = profile_id

    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    write_yaml_to_file(state, state_path)
