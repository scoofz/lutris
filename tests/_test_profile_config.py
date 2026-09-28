import os
import tempfile
import unittest
from unittest.mock import patch

from lutris import settings
from lutris.config import LutrisConfig
from lutris.database import games as games_db
from lutris.database import profiles as profiles_db
from lutris.database import schema
from lutris.migrations import migrate_profile_game_configs
from lutris.profile import ProfileManager
from lutris.util.test_config import setup_test_environment
from lutris.util.yaml import read_yaml_from_file, write_yaml_to_file

setup_test_environment()

CONFIG_ID = "mygame-1"
INSTALLED_GAME = {"exe": "/opt/games/mygame/drive_c/Game/game.exe", "prefix": "/opt/games/mygame"}


class ProfileConfigTester(unittest.TestCase):
    def setUp(self):
        if os.path.exists(settings.DB_PATH):
            os.remove(settings.DB_PATH)
        schema.syncdb()
        self.tmpdir = tempfile.TemporaryDirectory()
        config_dir = os.path.join(self.tmpdir.name, "config")
        game_config_dir = os.path.join(config_dir, "games")
        os.makedirs(game_config_dir)
        for name, value in (
            ("CONFIG_DIR", config_dir),
            ("GAME_CONFIG_DIR", game_config_dir),
            ("PROFILES_DIR", os.path.join(self.tmpdir.name, "profiles")),
        ):
            patcher = patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.tmpdir.cleanup)

        self.profile_manager = ProfileManager()
        patcher = patch.object(ProfileManager, "_instance", self.profile_manager)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.alice = profiles_db.add_profile("Alice")
        self.bob = profiles_db.add_profile("Bob")

        self.shared_config_path = os.path.join(game_config_dir, "%s.yml" % CONFIG_ID)
        write_yaml_to_file({"game": dict(INSTALLED_GAME), "wine": {"version": "wine-ge"}}, self.shared_config_path)
        games_db.add_game(name="My Game", slug="mygame", runner="wine", configpath=CONFIG_ID, installed=1)

    def get_config(self, profile_id):
        return LutrisConfig(runner_slug="wine", game_config_id=CONFIG_ID, profile_id=profile_id)

    def profile_config_path(self, profile_id):
        return self.profile_manager.get_profile_game_config_path(CONFIG_ID, profile_id)


class TestProfileConfigSave(ProfileConfigTester):
    def test_save_keeps_installation_in_shared_config(self):
        self.get_config(self.alice).save()
        self.assertEqual(read_yaml_from_file(self.shared_config_path)["game"], INSTALLED_GAME)
        self.assertFalse(os.path.exists(self.profile_config_path(self.alice)))
        bob_config = self.get_config(self.bob)
        self.assertEqual(bob_config.game_config["exe"], INSTALLED_GAME["exe"])
        self.assertEqual(bob_config.game_config["prefix"], INSTALLED_GAME["prefix"])

    def test_changed_installation_path_goes_to_shared_config(self):
        config = self.get_config(self.alice)
        config.game_level["game"]["exe"] = "/opt/games/mygame/drive_c/Game/other.exe"
        config.save()
        self.assertEqual(self.get_config(self.bob).game_config["exe"], "/opt/games/mygame/drive_c/Game/other.exe")

    def test_profile_specific_option_stays_in_profile(self):
        config = self.get_config(self.alice)
        config.game_level["game"]["args"] = "-user alice"
        config.save()
        self.assertEqual(read_yaml_from_file(self.profile_config_path(self.alice)), {"game": {"args": "-user alice"}})
        self.assertNotIn("args", read_yaml_from_file(self.shared_config_path)["game"])
        self.assertEqual(self.get_config(self.alice).game_config["args"], "-user alice")
        self.assertNotIn("args", self.get_config(self.bob).game_config)


class TestProfileConfigMigration(ProfileConfigTester):
    def test_restores_installation_paths_moved_to_a_profile(self):
        # State left by the previous save(): the game section only exists in Alice's profile
        write_yaml_to_file({"wine": {"version": "wine-ge"}}, self.shared_config_path)
        os.makedirs(os.path.dirname(self.profile_config_path(self.alice)))
        write_yaml_to_file({"game": dict(INSTALLED_GAME, args="-user alice")}, self.profile_config_path(self.alice))

        migrate_profile_game_configs.migrate()

        self.assertEqual(read_yaml_from_file(self.shared_config_path)["game"], INSTALLED_GAME)
        self.assertEqual(read_yaml_from_file(self.profile_config_path(self.alice)), {"game": {"args": "-user alice"}})
        self.assertEqual(self.get_config(self.bob).game_config["prefix"], INSTALLED_GAME["prefix"])
