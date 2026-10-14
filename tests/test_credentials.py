import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cryptography.fernet import Fernet

from mysport import credentials as c


class CredentialsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.secrets = self.root / "secrets"
        self.secrets.mkdir()
        env = {"MYSPORT_DATA_DIR": str(self.root / "data")}
        self.env = mock.patch.dict(os.environ, env, clear=False)
        self.env.start()
        for k in ("MYSPORT_KEY_FILE", "CREDENTIALS_DIRECTORY"):
            os.environ.pop(k, None)
        # /run/secrets des Testrechners darf nicht hineinspielen
        self.docker = mock.patch.object(c, "DOCKER_SECRETS_DIR", self.root / "none")
        self.docker.start()

    def tearDown(self):
        self.docker.stop()
        self.env.stop()
        self.tmp.cleanup()

    def test_vault_roundtrip_and_permissions(self):
        key = c.init_key()
        c.set_credentials("max@uni-bonn.de", "geh eim!", "default")
        self.assertEqual(c.get_credentials(), c.Credentials("max@uni-bonn.de", "geh eim!"))
        for p in (key, self.root / "data" / "vault.enc"):
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        self.assertNotIn(b"geh eim", (self.root / "data" / "vault.enc").read_bytes())

    def test_repr_hides_password(self):
        self.assertNotIn("geheim", repr(c.Credentials("a@b.de", "geheim")))

    def test_missing_credentials(self):
        c.init_key()
        with self.assertRaises(c.CredentialError):
            c.get_credentials("anna")

    def test_secret_files_win_over_vault(self):
        c.init_key()
        c.set_credentials("vault@b.de", "v")
        (self.secrets / "mysport_email").write_text("file@b.de\n")
        (self.secrets / "mysport_password").write_text("f p\n")
        os.environ["CREDENTIALS_DIRECTORY"] = str(self.secrets)
        self.assertEqual(c.get_credentials(), c.Credentials("file@b.de", "f p"))
        self.assertIn("Secret-Dateien", c.credentials_source())

    def test_key_from_secret_dir(self):
        (self.secrets / "mysport_key").write_bytes(Fernet.generate_key())
        os.environ["CREDENTIALS_DIRECTORY"] = str(self.secrets)
        c.set_credentials("a@b.de", "x")
        self.assertFalse((self.root / "data" / "key").exists())
        self.assertEqual(c.get_credentials().email, "a@b.de")
        with self.assertRaises(c.CredentialError):
            c.rotate_key()  # schreibgeschützt verwaltet

    def test_wrong_key(self):
        c.init_key()
        c.set_credentials("a@b.de", "x")
        (self.root / "data" / "key").write_bytes(Fernet.generate_key())
        with self.assertRaises(c.CredentialError):
            c.get_credentials()

    def test_sessions(self):
        c.init_key()
        self.assertIsNone(c.load_session())
        state = {"cookies": [{"name": "remember_web_x", "value": "abc"}]}
        c.save_session(state)
        self.assertEqual(c.load_session(), state)
        c.clear_session()
        self.assertIsNone(c.load_session())

    def test_rotate_key(self):
        c.init_key()
        c.set_credentials("a@b.de", "x", "anna")
        c.save_session({"s": 1}, "anna")
        old = (self.root / "data" / "key").read_bytes()
        c.rotate_key()
        self.assertNotEqual(old, (self.root / "data" / "key").read_bytes())
        self.assertEqual(c.get_credentials("anna").password, "x")
        self.assertEqual(c.load_session("anna"), {"s": 1})
        self.assertFalse((self.root / "data" / "key.old").exists())

    def test_delete_and_profile_validation(self):
        c.init_key()
        c.set_credentials("a@b.de", "x", "anna")
        c.save_session({"s": 1}, "anna")
        self.assertEqual(c.list_profiles(), ["anna"])
        self.assertTrue(c.delete_credentials("anna"))
        self.assertIsNone(c.load_session("anna"))
        with self.assertRaises(c.CredentialError):
            c.set_credentials("a@b.de", "x", "../evil")

    def test_cli(self):
        c.main(["init"])
        with mock.patch("sys.stdin.readline", return_value="pw\n"):
            c.main(["set", "--email", "max@uni-bonn.de", "--password-stdin"])
        self.assertEqual(c.get_credentials().password, "pw")
        self.assertEqual(c._mask("max@uni-bonn.de"), "ma***@uni-bonn.de")


if __name__ == "__main__":
    unittest.main()
