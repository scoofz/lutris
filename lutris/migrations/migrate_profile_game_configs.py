"""Repair game configs split between the shared config and profile overrides.

Earlier versions of the profile support moved the whole 'game' section (exe,
prefix, ...) of a game config into the active profile's override file when the
game was saved. Other profiles then lost the installation paths and fell back
to an empty per-profile Wine prefix, which led to the game being installed again.
"""

import glob
import os

from lutris import settings
from lutris.config import get_shared_game_options
from lutris.database.games import get_game_by_field
from lutris.util.log import logger
from lutris.util.yaml import read_yaml_from_file, write_yaml_to_file


def migrate():
    profile_config_paths = sorted(glob.glob(os.path.join(settings.PROFILES_DIR, "*", "games", "*.yml")))
    for profile_config_path in profile_config_paths:
        configpath = os.path.splitext(os.path.basename(profile_config_path))[0]
        shared_config_path = os.path.join(settings.GAME_CONFIG_DIR, "%s.yml" % configpath)
        if not os.path.exists(shared_config_path):
            continue
        game = get_game_by_field(configpath, "configpath")
        shared_options = get_shared_game_options(game["runner"] if game else None)

        profile_config = read_yaml_from_file(profile_config_path)
        shared_config = read_yaml_from_file(shared_config_path)
        profile_game = profile_config.get("game") or {}
        shared_game = shared_config.get("game") or {}

        restored = False
        overrides = {}
        for key, value in profile_game.items():
            if key in shared_options:
                if value and not shared_game.get(key):
                    shared_game[key] = value
                    restored = True
            elif shared_game.get(key) != value:
                overrides[key] = value

        if restored:
            logger.info("Restoring installation paths of %s from %s", configpath, profile_config_path)
            shared_config["game"] = shared_game
            write_yaml_to_file(shared_config, shared_config_path)
        if overrides:
            write_yaml_to_file({"game": overrides}, profile_config_path)
        else:
            os.remove(profile_config_path)
