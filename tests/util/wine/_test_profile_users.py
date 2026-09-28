import os
import tempfile
import unittest
from unittest.mock import patch

from lutris import settings
from lutris.util.wine import profile_users


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def read_file(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestIsolateUserFolder(unittest.TestCase):
    def setUp(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.root = tmpdir.name
        for patcher in (
            patch.object(settings, "PROFILES_DIR", os.path.join(self.root, "profiles")),
            patch.dict(os.environ, {"USER": "alice_unix"}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.prefix = os.path.join(self.root, "opt", "games", "mygame")
        self.users_dir = os.path.join(self.prefix, "drive_c", "users")
        self.user_path = os.path.join(self.users_dir, "alice_unix")
        self.save_path = os.path.join(self.user_path, "Saved Games", "MyGame", "save1.sav")
        write_file(self.save_path, "original progress")
        os.makedirs(os.path.join(self.users_dir, "Public"))

    def isolate(self, profile_id):
        return profile_users.isolate_user_folder(self.prefix, profile_id)

    def test_first_isolation_keeps_existing_saves(self):
        user_dir = self.isolate("alice")
        self.assertTrue(os.path.islink(self.user_path))
        self.assertEqual(os.readlink(self.user_path), user_dir)
        self.assertEqual(read_file(self.save_path), "original progress")
        template_save = os.path.join(self.prefix, profile_users.TEMPLATE_DIRNAME, "alice_unix", "Saved Games")
        self.assertTrue(os.path.isdir(template_save))
        self.assertFalse(os.path.islink(os.path.join(self.users_dir, "Public")))

    def test_each_profile_gets_its_own_copy(self):
        self.isolate("alice")
        write_file(self.save_path, "alice progress")
        self.isolate("bob")
        self.assertEqual(read_file(self.save_path), "original progress")
        write_file(self.save_path, "bob progress")
        self.isolate("alice")
        self.assertEqual(read_file(self.save_path), "alice progress")
        self.isolate("bob")
        self.assertEqual(read_file(self.save_path), "bob progress")

    def test_proton_user_link_follows_the_profile(self):
        proton_path = os.path.join(self.users_dir, "steamuser")
        os.symlink(self.user_path, proton_path)
        self.isolate("alice")
        write_file(os.path.join(proton_path, "file.txt"), "alice")
        self.isolate("bob")
        self.assertFalse(os.path.exists(os.path.join(proton_path, "file.txt")))

    def test_proton_compatdata_prefix(self):
        compatdata = os.path.join(self.root, "compatdata")
        os.makedirs(compatdata)
        os.rename(self.prefix, os.path.join(compatdata, "pfx"))
        user_dir = profile_users.isolate_user_folder(compatdata, "alice")
        self.assertEqual(user_dir, profile_users.get_profile_user_dir(os.path.join(compatdata, "pfx"), "alice"))
        self.assertTrue(os.path.islink(os.path.join(compatdata, "pfx", "drive_c", "users", "alice_unix")))

    def test_prefix_private_to_a_profile_is_left_alone(self):
        private_prefix = os.path.join(settings.PROFILES_DIR, "alice", "wine-prefixes", "mygame")
        os.makedirs(os.path.join(private_prefix, "drive_c", "users", "alice_unix"))
        self.assertIsNone(profile_users.isolate_user_folder(private_prefix, "alice"))
        self.assertFalse(os.path.islink(os.path.join(private_prefix, "drive_c", "users", "alice_unix")))

    def test_failed_copy_restores_the_prefix(self):
        with patch.object(profile_users.shutil, "copytree", side_effect=OSError("No space left on device")):
            with self.assertRaises(OSError):
                self.isolate("alice")
        self.assertFalse(os.path.islink(self.user_path))
        self.assertEqual(read_file(self.save_path), "original progress")
        self.assertFalse(os.path.exists(os.path.join(self.prefix, profile_users.TEMPLATE_DIRNAME, "alice_unix")))
        self.isolate("alice")
        self.assertEqual(read_file(self.save_path), "original progress")
