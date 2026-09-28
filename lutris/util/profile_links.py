"""Make a shared file or folder point to a copy owned by a Lutris profile.

The shared path becomes a symlink to the active profile's copy. The first time a
path is isolated, its original content is kept as a template, and every profile
starts from a full copy of that template.
"""

import os
import shutil

from lutris.util.log import logger


def _copy(source: str, destination: str) -> None:
    """Copy a file or folder, going through a temporary path so an interrupted
    copy never looks complete."""
    partial_path = destination + ".partial"
    _remove(partial_path)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    if os.path.isdir(source):
        shutil.copytree(source, partial_path, symlinks=True)
    else:
        shutil.copy2(source, partial_path, follow_symlinks=False)
    os.rename(partial_path, destination)


def _remove(path: str) -> None:
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    elif os.path.lexists(path):
        os.unlink(path)


def _replace(source: str, destination: str) -> None:
    """Move source over destination, which is only removed once source is in place."""
    new_path = destination + ".new"
    _remove(new_path)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    shutil.move(source, new_path)
    _remove(destination)
    os.rename(new_path, destination)


def link_to_profile(
    shared_path: str,
    template_path: str,
    profile_path: str,
    previous_profile_path: str | None = None,
) -> None:
    """Replace shared_path by a symlink to profile_path.

    - A real file or folder at shared_path is moved to template_path the first
      time. If it shows up again while previous_profile_path is given, the program
      replaced the symlink (e.g. by writing a new file and renaming it over the old
      one): this content is then the latest data of that previous profile.
    - profile_path is created as a copy of the template, or as an empty folder when
      there is no template.
    - If anything fails after the original content was moved, it is put back.
    """
    moved_to_template = False
    if os.path.lexists(shared_path) and not os.path.islink(shared_path):
        if previous_profile_path:
            logger.info("Moving %s back to %s, where it belongs", shared_path, previous_profile_path)
            _replace(shared_path, previous_profile_path)
        else:
            if os.path.lexists(template_path):
                raise RuntimeError("Can't isolate %s: %s already exists" % (shared_path, template_path))
            logger.info("Moving %s to %s to share it between profiles", shared_path, template_path)
            os.makedirs(os.path.dirname(template_path), exist_ok=True)
            os.rename(shared_path, template_path)
            moved_to_template = True

    try:
        if not os.path.lexists(profile_path):
            if os.path.lexists(template_path):
                logger.info("Creating %s from %s", profile_path, template_path)
                _copy(template_path, profile_path)
            else:
                os.makedirs(profile_path)
        if os.path.islink(shared_path):
            if os.readlink(shared_path) == profile_path:
                return
            os.unlink(shared_path)
        os.makedirs(os.path.dirname(shared_path), exist_ok=True)
        os.symlink(profile_path, shared_path, target_is_directory=os.path.isdir(profile_path))
    except Exception:
        if moved_to_template and not os.path.lexists(shared_path):
            os.rename(template_path, shared_path)
        raise
    logger.debug("Linked %s to %s", shared_path, profile_path)
