"""
The sidebar rules of the Admin page, as they are written in the style (lab_ui.ADMIN).

This is the fast guard: it does not measure pixels (that is sidebar_check.py, which opens a real browser and
checks the four rules at 1366 and 1920 wide in light and dark mode). It fails when a rule is taken out of the
style, or when the "!important" that holds it against Streamlit's own styles is lost.

  py -3.12 -m unittest test_sidebar_rules -v
"""

import re
import unittest

import lab_text as T
import lab_ui as UI

CSS = re.sub(r"/\*.*?\*/", "", UI.ADMIN, flags=re.S)          # the comments talk about the rules too: left out
STAR = "\u2605"                                                # the star of "★ ADMIN"


def blocks(selector, css=CSS):
    """The declarations of every rule whose selector part contains `selector`."""
    return [" ".join(m.group(2).split()) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)
            if selector in " ".join(m.group(1).split())]


def block(selector, css=CSS):
    """The declarations of the first rule for `selector` ('' when there is none)."""
    found = blocks(selector, css)
    return found[0] if found else ""


class TestSidebarStyle(unittest.TestCase):
    def check(self, selector, *fragments):
        """One rule of `selector` holds every fragment."""
        found = blocks(selector)
        self.assertTrue(found, f"no rule for {selector} in lab_ui.ADMIN")
        for fragment in fragments:
            with self.subTest(selector=selector, fragment=fragment):
                self.assertTrue(any(fragment in block_text for block_text in found),
                                f"{selector} lost '{fragment}'")

    # --- the sidebar itself -------------------------------------------------------------------------------------
    def test_the_sidebar_keeps_its_width_and_never_scrolls_sideways(self):
        self.check('section[data-testid="stSidebar"]', "248px !important", "overflow-x: hidden !important")
        self.check('[data-testid="stSidebarContent"]', "overflow-x: hidden !important", "scrollbar-gutter: auto")

    def test_the_side_padding_of_the_sidebar_is_the_same_for_everything(self):
        self.check('[data-testid="stSidebarUserContent"]', "padding: 20px 16px 18px 16px !important")

    # --- R1: the badge on its own line --------------------------------------------------------------------------
    def test_the_badge_is_a_block_on_its_own_line_with_a_small_space_above_it(self):
        self.check(".a-brand .lab", "display: block")
        self.check(".a-brand .badge", "display: block", "width: max-content", "margin-top: 8px")

    def test_the_brand_keeps_room_for_the_fold_button(self):
        self.check(".a-brand", "padding: 0 44px 16px 10px")

    def test_the_badge_and_the_words_are_the_ones_the_rule_talks_about(self):
        self.assertEqual(T.ADMIN_TEXT["lab"], "ATS LAB")
        self.assertTrue(T.ADMIN_TEXT["admin_badge"].endswith("ADMIN"))
        self.assertEqual(T.ADMIN_TEXT["admin_badge"][0], STAR)

    # --- R2: the open menu item ---------------------------------------------------------------------------------
    def test_every_menu_item_keeps_the_same_box_and_padding(self):
        self.check('[class*="st-key-nav_"] button', "width: 100% !important", "padding: 8px 10px !important",
                   "box-sizing: border-box", "overflow: hidden")

    # --- R3: the profile card -----------------------------------------------------------------------------------
    def test_the_profile_card_can_never_leave_the_sidebar(self):
        self.check(".st-key-side-card", "width: 100% !important", "max-width: 100% !important",
                   "box-sizing: border-box", "overflow: hidden")
        self.check(".st-key-side-foot", "width: 100% !important", "max-width: 100% !important")
        self.check(".a-ver", "max-width: 100%")

    # --- R4: the fold button ------------------------------------------------------------------------------------
    def test_the_fold_button_is_always_visible_on_the_line_of_the_brand(self):
        self.check('[data-testid="stSidebarCollapseButton"]', "position: absolute", "top: 23px", "right: 14px",
                   "visibility: visible !important", "opacity: 1 !important", "pointer-events: auto")

    def test_the_header_of_the_sidebar_cannot_take_the_clicks_of_the_brand(self):
        self.check('[data-testid="stSidebarHeader"]', "position: absolute", "pointer-events: none")

    def test_the_fold_button_has_its_own_place_on_the_right(self):
        """32px of button at right 14px, and 44px of free room in the brand: they cannot meet."""
        button = float(re.search(r"width: (\d+)px", block('[data-testid="stSidebarCollapseButton"]')).group(1))
        right = float(re.search(r"right: (\d+)px", block('[data-testid="stSidebarCollapseButton"]')).group(1))
        free = float(re.search(r"padding: 0 (\d+)px", block(".a-brand")).group(1))
        self.assertGreaterEqual(free, button + 10, "the brand must keep more room than the button needs")
        self.assertLessEqual(right + button, 44 + 10, "the button must stay in its place on the right")


if __name__ == "__main__":
    unittest.main()
