import os
import unittest
from unittest.mock import patch

from local_config import address_from_seed, local_endpoints, peer_address

SEED = "a" * 64


class PeerAddressTests(unittest.TestCase):
    def test_local_mode_prefers_seed(self):
        with patch.dict(os.environ, {"DAOTHINK_LOCAL": "1", "X_SEED": SEED, "X_ADDR": "explicit"}):
            self.assertEqual(peer_address("X_ADDR", "X_SEED"), address_from_seed(SEED))

    def test_hosted_mode_prefers_explicit_then_seed(self):
        with patch.dict(os.environ, {"DAOTHINK_LOCAL": "0", "X_SEED": SEED, "X_ADDR": "explicit"}):
            self.assertEqual(peer_address("X_ADDR", "X_SEED"), "explicit")
        with patch.dict(os.environ, {"DAOTHINK_LOCAL": "0", "X_SEED": SEED, "X_ADDR": ""}):
            self.assertEqual(peer_address("X_ADDR", "X_SEED"), address_from_seed(SEED))
        with patch.dict(os.environ, {"DAOTHINK_LOCAL": "0", "X_SEED": "", "X_ADDR": ""}):
            self.assertEqual(peer_address("X_ADDR", "X_SEED"), "")

    def test_addresses_are_real_agent_addresses_on_distinct_ports(self):
        self.assertTrue(address_from_seed(SEED).startswith("agent1"))
        endpoints = local_endpoints()
        ports = sorted(url.split(":")[2].split("/")[0] for url in endpoints.values())
        self.assertEqual(ports, ["8000", "8001", "8002", "8003"])
        self.assertTrue(all(url.startswith("http://127.0.0.1:") for url in endpoints.values()))


if __name__ == "__main__":
    unittest.main()
