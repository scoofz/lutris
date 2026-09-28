"""Give each Lutris profile its own Windows user folder inside a shared Wine prefix.

The game stays installed once in the shared prefix, but drive_c/users/<user>
(Documents, Saved Games, AppData, ...) becomes a symlink to a folder owned by the
active profile:

    ~/.local/share/lutris/profiles/<profile>/wine-users/<prefix key>/<user>

The first time a prefix is isolated, its original user folder is moved to
<prefix>/lutris-profile-template/<user>. Every profile then starts from a full
copy of that template the first time it launches a game from this prefix.
"""

import hashlib
import os
import shutil

from lutris import settings
from lutris.util.log import logger

TEMPLATE_DIRNAME = "lutris-profile-template"
PROTON_USER = "steamuser"


def get_wine_user_name() -> str:
    """Name of the Windows user folder Wine creates for the current user."""
    return os.getenv("USER") or "lutrisuser"


def resolve_prefix_path(prefix_path: str) -> str:
    """Absolute path of the folder containing drive_c (the 'pfx' folder for Proton)."""
    prefix_path = os.path.abspath(os.path.expanduser(prefix_path))
    pfx_path = os.path.join(prefix_path, "pfx")
    if os.path.isdir(os.path.join(pfx_path, "drive_c")):
        return pfx_path
    return prefix_path


def get_prefix_key(prefix_path: str) -> str:
    """Stable, readable identifier for a prefix; games sharing a prefix share it."""
    prefix_path = resolve_prefix_path(prefix_path)
    digest = hashlib.sha1(prefix_path.encode("utf-8")).hexdigest()[:8]
    name = os.path.basename(prefix_path)
    if name == "pfx":
        name = os.path.basename(os.path.dirname(prefix_path))
    return "%s-%s" % (name or "prefix", digest)


def get_profile_user_dir(prefix_path: str, profile_id: str, user_name: str | None = None) -> str:
    """Folder holding the Windows user folder of a profile for this prefix."""
    return os.path.join(
        settings.PROFILES_DIR,
        profile_id,
        "wine-users",
        get_prefix_key(prefix_path),
        user_name or get_wine_user_name(),
    )


def get_wine_user_dir_in_prefix(prefix_path: str) -> str:
    """Windows user folder of a prefix that is private to a profile."""
    return os.path.join(resolve_prefix_path(prefix_path), "drive_c", "users", get_wine_user_name())


def is_in_profiles_dir(path: str) -> bool:
    profiles_dir = os.path.abspath(settings.PROFILES_DIR)
    return os.path.abspath(path).startswith(profiles_dir + os.sep)


def _find_user_folder(users_dir: str) -> str | None:
    """Return the name of the user folder to isolate in drive_c/users.

    Wine uses $USER while Proton uses 'steamuser'; Lutris links one to the other,
    so only one of them is a real folder (or an already isolated profile link)."""
    names = [get_wine_user_name(), PROTON_USER]
    for name in names:
        path = os.path.join(users_dir, name)
        if os.path.islink(path) and is_in_profiles_dir(os.readlink(path)):
            return name
    for name in names:
        path = os.path.join(users_dir, name)
        if os.path.isdir(path) and not os.path.islink(path):
            return name
    return None


def isolate_user_folder(prefix_path: str, profile_id: str) -> str | None:
    """Point the prefix's Windows user folder to the one of the given profile.

    Returns the profile's user folder, or None when the prefix has no user folder
    to isolate (yet) or is already private to a profile."""
    prefix_path = resolve_prefix_path(prefix_path)
    if is_in_profiles_dir(prefix_path):
        return None
    users_dir = os.path.join(prefix_path, "drive_c", "users")
    user_name = _find_user_folder(users_dir)
    if not user_name:
        return None

    user_path = os.path.join(users_dir, user_name)
    template_path = os.path.join(prefix_path, TEMPLATE_DIRNAME, user_name)
    profile_user_dir = get_profile_user_dir(prefix_path, profile_id, user_name)

    moved_to_template = False
    if not os.path.islink(user_path):
        if os.path.exists(template_path):
            raise RuntimeError("Can't isolate %s: %s already exists" % (user_path, template_path))
        logger.info("Moving %s to %s to share it between profiles", user_path, template_path)
        os.makedirs(os.path.dirname(template_path), exist_ok=True)
        os.rename(user_path, template_path)
        moved_to_template = True

    try:
        if not os.path.isdir(profile_user_dir):
            _create_profile_user_dir(template_path, profile_user_dir)
        if os.path.islink(user_path):
            if os.readlink(user_path) == profile_user_dir:
                return profile_user_dir
            os.unlink(user_path)
        os.symlink(profile_user_dir, user_path, target_is_directory=True)
    except Exception:
        if moved_to_template and not os.path.lexists(user_path):
            # Put the prefix back as it was rather than letting Wine create an empty user folder
            os.rename(template_path, user_path)
        raise
    logger.debug("Linked %s to %s", user_path, profile_user_dir)
    return profile_user_dir


def _create_profile_user_dir(template_path: str, profile_user_dir: str) -> None:
    """Create a profile's user folder as a full copy of the prefix's template."""
    os.makedirs(os.path.dirname(profile_user_dir), exist_ok=True)
    if not os.path.isdir(template_path):
        os.makedirs(profile_user_dir)
        return
    logger.info("Creating %s from %s", profile_user_dir, template_path)
    partial_dir = profile_user_dir + ".partial"
    shutil.rmtree(partial_dir, ignore_errors=True)
    shutil.copytree(template_path, partial_dir, symlinks=True)
    os.rename(partial_dir, profile_user_dir)
