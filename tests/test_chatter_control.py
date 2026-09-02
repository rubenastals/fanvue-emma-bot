"""Tests for chatter pause control."""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch


class ChatterControlTests(unittest.TestCase):
    def test_env_disabled(self):
        from core import chatter_control as cc

        with patch.dict(os.environ, {"CHATTER_ENABLED": "0"}):
            self.assertFalse(cc.chatter_enabled_env())
            self.assertTrue(cc.is_chatter_paused("emma"))

    def test_account_inactive_pauses(self):
        from core import chatter_control as cc

        with patch.object(cc, "is_account_active", return_value=False):
            with patch.object(cc, "chatter_enabled_env", return_value=True):
                with patch.object(cc, "_redis", return_value=None):
                    self.assertTrue(cc.is_chatter_paused("emma"))

    def test_redis_global_pause(self):
        from core import chatter_control as cc

        r = MagicMock()
        r.exists.side_effect = lambda k: k == cc._GLOBAL_KEY
        with patch.object(cc, "chatter_enabled_env", return_value=True):
            with patch.object(cc, "is_account_active", return_value=True):
                with patch.object(cc, "_redis", return_value=r):
                    self.assertTrue(cc.is_chatter_paused("emma"))


if __name__ == "__main__":
    unittest.main()
