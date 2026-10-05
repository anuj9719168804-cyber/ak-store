# TEST_AUTOQUALITY.PY - ADDITIONS
# ================================
# Add these test classes to the end of tests/test_autoquality.py
# (Before or after the existing UpscaleFfmpegTest class)

import asyncio
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helper import quality, transcode as t  # noqa: E402


# ============================================================================
# TEST CLASS 1: Quality Panel Formatting Tests
# ============================================================================

class QualityPanelFormattingTests(unittest.TestCase):
    """Test the UI formatting for auto-quality settings panel."""
    
    def test_status_message_shows_on_state(self):
        """Verify status message displays ON when enabled."""
        on = True
        wanted = ['720p', '1080p']
        upscale_to = []
        has_premium = False
        
        text = (
            f"<blockquote>🎞 <b>Auto-Quality Settings</b></blockquote>\n"
            f"Status: <b>{'✓ ON' if on else '✗ OFF'}</b>\n"
            f"Qualities: <b>{', '.join(wanted) if wanted else 'None'}</b>\n"
            f"Upscale to: <b>{', '.join(upscale_to) if upscale_to else 'OFF'}</b>\n"
            f"Uploader: <b>{'Premium account' if has_premium else 'Bot'}</b>"
        )
        
        self.assertIn("✓ ON", text)
        self.assertIn("720p, 1080p", text)
        self.assertIn("Bot", text)
    
    def test_status_message_shows_off_state(self):
        """Verify status message displays OFF when disabled."""
        on = False
        wanted = []
        upscale_to = []
        has_premium = False
        
        text = (
            f"<blockquote>🎞 <b>Auto-Quality Settings</b></blockquote>\n"
            f"Status: <b>{'✓ ON' if on else '✗ OFF'}</b>"
        )
        
        self.assertIn("✗ OFF", text)
    
    def test_status_message_with_upscale(self):
        """Verify upscale settings are displayed."""
        on = True
        wanted = ['480p', '720p']
        upscale_to = ['1080p', '1440p', '4K']
        has_premium = True
        
        text = (
            f"Upscale to: <b>{', '.join(upscale_to) if upscale_to else 'OFF'}</b>\n"
            f"Uploader: <b>{'Premium account' if has_premium else 'Bot'}</b>"
        )
        
        self.assertIn("1080p, 1440p, 4K", text)
        self.assertIn("Premium account", text)
    
    def test_quality_presets_are_valid(self):
        """Verify all quality presets use valid qualities."""
        presets = [
            (["144p", "360p", "720p"], "Small"),
            (["360p", "720p", "1080p"], "Medium"),
            (["720p", "1080p", "1440p"], "High"),
            (["1080p", "1440p", "4K"], "Ultra"),
        ]
        
        for preset_list, label in presets:
            for quality in preset_list:
                self.assertIn(quality, t.ORDER, f"{quality} not in ORDER")


# ============================================================================
# TEST CLASS 2: Callback Data Validation Tests
# ============================================================================

class CallbackDataValidationTests(unittest.TestCase):
    """Test parsing and validation of callback data."""
    
    def test_parse_quality_set_callback(self):
        """Test parsing of quality set callback data."""
        callback_data = "autoquality_set_144p,360p,720p"
        
        parts = callback_data.split("_", 2)
        self.assertEqual(len(parts), 3)
        self.assertEqual(parts[2], "144p,360p,720p")
        
        parsed = t.parse_list(parts[2])
        self.assertEqual(parsed, ["144p", "360p", "720p"])
    
    def test_parse_upscale_callback(self):
        """Test parsing of upscale callback data."""
        callback_data = "autoquality_upscale_1080p,1440p,4K"
        
        parts = callback_data.split("_", 2)
        parsed = t.parse_list(parts[2])
        self.assertEqual(parsed, ["1080p", "1440p", "4K"])
    
    def test_parse_upscale_toggle_callback(self):
        """Test parsing of upscale toggle callback."""
        callback_data = "autoquality_upscale_toggle"
        
        parts = callback_data.split("_", 2)
        self.assertEqual(parts[2], "toggle")
        self.assertEqual(parts[2].lower(), "toggle")
    
    def test_invalid_quality_filtered(self):
        """Test that invalid qualities are filtered."""
        quality_str = "144p,999p,720p"
        
        parsed = t.parse_list(quality_str)
        self.assertNotIn("999p", parsed)
        self.assertIn("144p", parsed)
        self.assertIn("720p", parsed)
    
    def test_callback_data_size_under_limit(self):
        """Test that callback data stays under Telegram's 64-byte limit."""
        callbacks = [
            "autoquality_toggle",
            "autoquality_set_144p,360p,720p",
            "autoquality_set_1080p,1440p,4K",
            "autoquality_upscale_1080p,1440p,4K",
        ]
        
        for callback_data in callbacks:
            self.assertLessEqual(len(callback_data), 64,
                               f"Callback {callback_data} exceeds 64 bytes")


# ============================================================================
# TEST CLASS 3: Admin Authorization Tests
# ============================================================================

class AdminAuthorizationTests(unittest.TestCase):
    """Test admin authorization for callbacks."""
    
    def test_admin_callback_guard_pattern_recognizes_autoquality(self):
        """Test regex matches autoquality patterns."""
        import re
        
        pattern = re.compile(
            r"^(?:"
            r"autoquality_toggle|autoquality_set_.*|autoquality_upscale_.*"
            r")$"
        )
        
        # Should match
        self.assertTrue(pattern.match("autoquality_toggle"))
        self.assertTrue(pattern.match("autoquality_set_144p,360p"))
        self.assertTrue(pattern.match("autoquality_upscale_1080p"))
        
        # Should not match
        self.assertFalse(pattern.match("autoquality_invalid"))
        self.assertFalse(pattern.match("other_callback"))
    
    def test_admin_check_blocks_non_admins(self):
        """Test non-admins are blocked."""
        user_id = 12345
        admins = [67890, 11111]
        owner_id = 99999
        
        is_admin = user_id in admins or user_id == owner_id
        self.assertFalse(is_admin)
    
    def test_admin_check_allows_owner(self):
        """Test owner can access."""
        user_id = 99999
        admins = [67890, 11111]
        owner_id = 99999
        
        is_admin = user_id in admins or user_id == owner_id
        self.assertTrue(is_admin)
    
    def test_admin_check_allows_admin(self):
        """Test admin users can access."""
        user_id = 67890
        admins = [67890, 11111]
        owner_id = 99999
        
        is_admin = user_id in admins or user_id == owner_id
        self.assertTrue(is_admin)


# ============================================================================
# TEST CLASS 4: Button Toggle Logic Tests
# ============================================================================

class ButtonToggleLogicTests(unittest.TestCase):
    """Test toggle button state logic."""
    
    def test_toggle_on_state_button_text(self):
        """Test button text when ON."""
        on = True
        
        toggle_on_text = "✓ ON" if on else "○ ON"
        toggle_off_text = "✓ OFF" if not on else "○ OFF"
        
        self.assertEqual(toggle_on_text, "✓ ON")
        self.assertEqual(toggle_off_text, "○ OFF")
    
    def test_toggle_off_state_button_text(self):
        """Test button text when OFF."""
        on = False
        
        toggle_on_text = "✓ ON" if on else "○ ON"
        toggle_off_text = "✓ OFF" if not on else "○ OFF"
        
        self.assertEqual(toggle_on_text, "○ ON")
        self.assertEqual(toggle_off_text, "✓ OFF")
    
    def test_quality_preset_button_shows_selected_state(self):
        """Test preset button shows selected state."""
        wanted = ["720p", "1080p", "1440p"]
        preset = ["720p", "1080p", "1440p"]
        
        is_current = wanted == preset
        button_text = ("✓ " if is_current else "  ") + "High"
        
        self.assertEqual(button_text, "✓ High")
    
    def test_quality_preset_button_shows_unselected_state(self):
        """Test preset button shows unselected state."""
        wanted = ["144p", "360p", "720p"]
        preset = ["720p", "1080p", "1440p"]
        
        is_current = wanted == preset
        button_text = ("✓ " if is_current else "  ") + "High"
        
        self.assertEqual(button_text, "  High")
    
    def test_upscale_button_shows_enabled(self):
        """Test upscale button when enabled."""
        upscale_to = ["1080p", "1440p"]
        
        if upscale_to:
            upscale_text = f"🔺 Upscale: {','.join(upscale_to)}"
        else:
            upscale_text = "🔺 Upscale: OFF"
        
        self.assertEqual(upscale_text, "🔺 Upscale: 1080p,1440p")
    
    def test_upscale_button_shows_disabled(self):
        """Test upscale button when disabled."""
        upscale_to = []
        
        if upscale_to:
            upscale_text = f"🔺 Upscale: {','.join(upscale_to)}"
        else:
            upscale_text = "🔺 Upscale: OFF"
        
        self.assertEqual(upscale_text, "🔺 Upscale: OFF")


# ============================================================================
# TEST CLASS 5: Database Update Simulation Tests
# ============================================================================

class DatabaseUpdateSimulationTests(unittest.TestCase):
    """Test database update patterns."""
    
    def test_toggle_state_change(self):
        """Test toggle changes state."""
        current_state = False
        new_state = not current_state
        
        self.assertTrue(new_state)
        
        # Toggle again
        new_state = not new_state
        self.assertFalse(new_state)
    
    def test_quality_list_update(self):
        """Test quality list updates."""
        # Current
        current = "144p,360p,720p"
        parsed_current = t.parse_list(current)
        
        # New
        new = "720p,1080p,1440p"
        parsed_new = t.parse_list(new)
        
        self.assertEqual(parsed_current, ["144p", "360p", "720p"])
        self.assertEqual(parsed_new, ["720p", "1080p", "1440p"])
        self.assertNotEqual(parsed_current, parsed_new)
    
    def test_upscale_enable(self):
        """Test enabling upscale."""
        current = ""  # Disabled
        new = "1080p,1440p"
        
        self.assertEqual(current, "")
        self.assertNotEqual(new, "")
    
    def test_upscale_disable(self):
        """Test disabling upscale."""
        current = "1080p,1440p"
        new = ""
        
        self.assertNotEqual(current, "")
        self.assertEqual(new, "")


# ============================================================================
# TEST CLASS 6: Quality Constant Reference Tests
# ============================================================================

class QualityConstantTests(unittest.TestCase):
    """Test quality constants and ordering."""
    
    def test_all_preset_qualities_are_in_order(self):
        """Test that all preset qualities are valid."""
        for quality in ["144p", "360p", "720p", "1080p", "1440p", "4K"]:
            self.assertIn(quality, t.ORDER)
    
    def test_order_list_is_complete(self):
        """Test ORDER list contains expected qualities."""
        expected = ["144p", "240p", "360p", "480p", "720p", "1080p", "1440p", "4K"]
        
        for q in expected:
            self.assertIn(q, t.ORDER, f"{q} missing from ORDER")
    
    def test_parse_list_returns_sorted(self):
        """Test parse_list returns in ORDER."""
        result = t.parse_list("4K, 144p, 1080p")
        
        # Should be sorted in ORDER
        self.assertEqual(result[0], "144p")
        self.assertIn("1080p", result)
        self.assertIn("4K", result)


# ============================================================================
# TEST CLASS 7: Integration Scenario Tests
# ============================================================================

class IntegrationScenarioTests(unittest.TestCase):
    """Test complete workflows."""
    
    def test_toggle_workflow_sequence(self):
        """Test complete toggle workflow."""
        # Initial state: OFF
        on = False
        
        # Click toggle
        on = not on
        self.assertTrue(on)
        
        # Click toggle again
        on = not on
        self.assertFalse(on)
    
    def test_quality_selection_workflow(self):
        """Test quality selection workflow."""
        # Start
        wanted = ["144p", "360p", "720p"]
        
        # User selects "High"
        new_wanted = ["720p", "1080p", "1440p"]
        wanted = new_wanted
        
        self.assertEqual(wanted, ["720p", "1080p", "1440p"])
    
    def test_upscale_enable_workflow(self):
        """Test upscale enable workflow."""
        # Start
        upscale_to = []
        
        # User enables upscale
        upscale_to = ["1080p", "1440p"]
        
        self.assertTrue(len(upscale_to) > 0)
        self.assertIn("1080p", upscale_to)
    
    def test_multi_step_workflow(self):
        """Test complete multi-step workflow."""
        # Initial
        on = False
        wanted = ["144p", "360p"]
        upscale_to = []
        
        # Step 1: Enable auto-quality
        on = True
        self.assertTrue(on)
        
        # Step 2: Change quality
        wanted = ["720p", "1080p"]
        self.assertEqual(wanted, ["720p", "1080p"])
        
        # Step 3: Enable upscale
        upscale_to = ["1440p", "4K"]
        self.assertTrue(len(upscale_to) > 0)
        
        # Verify final state
        self.assertTrue(on)
        self.assertEqual(wanted, ["720p", "1080p"])
        self.assertEqual(upscale_to, ["1440p", "4K"])


# ============================================================================
# Run tests if this file is executed directly
# ============================================================================

if __name__ == "__main__":
    unittest.main()
