import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from lutris import settings
from lutris.util import profile_save_dirs
from lutris.util.profile_save_dirs import TEMPLATE_SUFFIX, expand_save_dir, link_game_save_dirs, parse_save_dirs


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def read_file(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestParseAndExpand(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_save_dirs(" $GAMEDIR/saves ; ~/x\n/opt/y;;"), ["$GAMEDIR/saves", "~/x", "/opt/y"])
        self.assertEqual(parse_save_dirs(None), [])

    def test_expand(self):
        self.assertEqual(expand_save_dir("$GAMEDIR/saves/", "/opt/games/g", None), "/opt/games/g/saves")
        self.assertEqual(expand_save_dir("saves", "/opt/games/g", None), "/opt/games/g/saves")
        self.assertEqual(expand_save_dir("$PREFIX/drive_c/ProgramData/G", None, "/p"), "/p/drive_c/ProgramData/G")
        self.assertEqual(expand_save_dir("~/.local/share/G", None, None), os.path.expanduser("~/.local/share/G"))
        self.assertIsNone(expand_save_dir("$PREFIX/x", "/opt/games/g", None))
        self.assertIsNone(expand_save_dir("saves", None, None))


class TestLinkGameSaveDirs(unittest.TestCase):
    def setUp(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.root = tmpdir.name
        patcher = patch.object(settings, "PROFILES_DIR", os.path.join(self.root, "profiles"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.game_dir = os.path.join(self.root, "opt", "games", "oldgame")
        self.prefix = os.path.join(self.root, "prefix")
        write_file(os.path.join(self.game_dir, "game.exe"), "binary")
        self.saves = os.path.join(self.game_dir, "saves")
        write_file(os.path.join(self.saves, "slot1.sav"), "original")
        self.options = {"profile_save_dirs": "$GAMEDIR/saves"}

    def link(self, profile_id):
        game = SimpleNamespace(
            directory=self.game_dir,
            config=SimpleNamespace(game_config={"exe": "game.exe"}),
            runner=SimpleNamespace(system_config=self.options, prefix_path=self.prefix),
        )
        link_game_save_dirs(game, profile_id)

    def test_each_profile_gets_its_own_copy(self):
        slot = os.path.join(self.saves, "slot1.sav")
        self.link("alice")
        self.assertTrue(os.path.islink(self.saves))
        self.assertEqual(read_file(os.path.join(self.saves + TEMPLATE_SUFFIX, "slot1.sav")), "original")
        write_file(slot, "alice")
        self.link("bob")
        self.assertEqual(read_file(slot), "original")
        write_file(slot, "bob")
        self.link("alice")
        self.assertEqual(read_file(slot), "alice")

    def test_missing_folder_is_created_empty_for_each_profile(self):
        self.options["profile_save_dirs"] = "$GAMEDIR/newsaves"
        self.link("alice")
        write_file(os.path.join(self.game_dir, "newsaves", "a.sav"), "alice")
        self.link("bob")
        self.assertEqual(os.listdir(os.path.join(self.game_dir, "newsaves")), [])

    def test_save_file_replaced_by_the_game_goes_back_to_its_profile(self):
        save_file = os.path.join(self.game_dir, "game.sav")
        write_file(save_file, "original")
        self.options["profile_save_dirs"] = "game.sav"
        self.link("alice")
        self.assertTrue(os.path.islink(save_file))
        # The game writes a new file and renames it over the symlink
        os.unlink(save_file)
        write_file(save_file, "alice")
        self.link("bob")
        self.assertEqual(read_file(save_file), "original")
        self.link("alice")
        self.assertEqual(read_file(save_file), "alice")

    def test_missing_file_is_left_alone(self):
        self.options["profile_save_dirs"] = "later.sav"
        self.link("alice")
        self.assertFalse(os.path.lexists(os.path.join(self.game_dir, "later.sav")))

    def test_refuses_paths_holding_the_game_or_prefix(self):
        self.options["profile_save_dirs"] = "$GAMEDIR;$GAMEDIR/..;$PREFIX;~;/"
        os.makedirs(self.prefix)
        self.link("alice")
        self.assertFalse(os.path.islink(self.game_dir))
        self.assertFalse(os.path.islink(self.prefix))
        self.assertTrue(os.path.isfile(os.path.join(self.game_dir, "game.exe")))

    def test_refuses_paths_already_private_to_a_profile(self):
        private_dir = os.path.join(settings.PROFILES_DIR, "alice", "stuff")
        os.makedirs(private_dir)
        os.symlink(os.path.join(settings.PROFILES_DIR, "alice"), os.path.join(self.game_dir, "userlink"))
        self.options["profile_save_dirs"] = "$GAMEDIR/userlink/stuff"
        self.link("bob")
        self.assertFalse(os.path.islink(private_dir))

    def test_state_remembers_the_last_profile(self):
        self.link("alice")
        state = profile_save_dirs.read_yaml_from_file(profile_save_dirs.get_state_path())
        self.assertEqual(state, {self.saves: "alice"})
