from __future__ import annotations

import unittest

from transcription_v2.delivery_tokens import DeliveryTokenSigner, InvalidDeliveryToken


class DeliveryTokenTests(unittest.TestCase):
    def test_round_trip_scoped_grant(self) -> None:
        signer = DeliveryTokenSigner(b"a sufficiently long test secret", clock=lambda: 1000)
        token, expires_at = signer.issue(
            job_id="job123",
            owner_key="owner123",
            artifact="delivery.zip",
            purge_after_delivery=True,
            lifetime_seconds=60,
        )
        grant = signer.verify(token)
        self.assertEqual(expires_at, 1060)
        self.assertEqual(grant.job_id, "job123")
        self.assertTrue(grant.purge_after_delivery)

    def test_tamper_and_expiry_are_rejected(self) -> None:
        current = [1000.0]
        signer = DeliveryTokenSigner(b"a sufficiently long test secret", clock=lambda: current[0])
        token, _ = signer.issue(
            job_id="job123",
            owner_key="owner123",
            artifact="delivery.zip",
            lifetime_seconds=30,
        )
        with self.assertRaises(InvalidDeliveryToken):
            signer.verify(token + "x")
        current[0] = 1031
        with self.assertRaises(InvalidDeliveryToken):
            signer.verify(token)


if __name__ == "__main__":
    unittest.main()
