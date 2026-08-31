from __future__ import annotations

import unittest

from transcription_v2.auth import AuthenticationError, authenticate, owner_key


class AuthTests(unittest.TestCase):
    def test_token_is_required_when_configured(self) -> None:
        with self.assertRaises(AuthenticationError):
            authenticate(configured_token="secret", authorization=None, claimed_owner="alex")

    def test_valid_token_and_owner(self) -> None:
        owner = authenticate(
            configured_token="secret",
            authorization="Bearer secret",
            claimed_owner="alex@example.org",
        )
        self.assertEqual(owner, "alex@example.org")

    def test_owner_key_is_opaque_and_stable(self) -> None:
        self.assertEqual(owner_key("alex"), owner_key("alex"))
        self.assertNotIn("alex", owner_key("alex"))


if __name__ == "__main__":
    unittest.main()
