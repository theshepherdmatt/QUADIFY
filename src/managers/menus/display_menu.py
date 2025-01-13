# src/managers/menus/display_menu.py

import logging
import time
from PIL import ImageFont
from managers.menus.base_manager import BaseManager

class DisplayMenu(BaseManager):
    """
    A text-list menu for picking which display style to use:
      - Modern
      - Original
      - VU-Meter
      - Brightness
      Optionally: A sub-menu for "Modern" to toggle "Spectrum" on/off.
    """

    def __init__(
        self,
        display_manager,
        mode_manager,
        window_size=4,
        y_offset=2,
        line_spacing=15
    ):
        super().__init__(display_manager, None, mode_manager)

        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.DEBUG)

        self.mode_manager     = mode_manager
        self.display_manager = display_manager
        self.is_active       = False

        # Font for text
        self.font_key = "menu_font"
        self.font = self.display_manager.fonts.get(self.font_key) or ImageFont.load_default()

        # Main display menu items
        self.display_items = ["Modern", "Original", "VU-Screen", "Brightness"]
        self.current_index = 0

        # Layout
        self.window_size   = window_size
        self.y_offset      = y_offset
        self.line_spacing  = line_spacing

        # Debounce
        self.last_action_time   = 0
        self.debounce_interval = 0.3

        # Menu stack if you want sub-sub-menus
        self.menu_stack = []
        self.submenu_active = False
        self.current_submenu_name = None  # track which submenu we're in

    # -------------------------------------------------------
    # Activation / Deactivation
    # -------------------------------------------------------
    def start_mode(self):
        if self.is_active:
            self.logger.debug("DisplayMenu: Already active.")
            return
        self.is_active = True
        self.logger.info("DisplayMenu: Starting display selection menu.")
        self.show_items_list()

    def stop_mode(self):
        if self.is_active:
            self.is_active = False
            self.display_manager.clear_screen()
            self.logger.info("DisplayMenu: Stopped and cleared display.")

    # -------------------------------------------------------
    # Display
    # -------------------------------------------------------
    def show_items_list(self):
        """
        Renders the list of current menu items, highlighting the selection.
        """
        def draw(draw_obj):
            for i, name in enumerate(self.display_items):
                arrow = "-> " if i == self.current_index else "   "
                fill_color = "white" if i == self.current_index else "gray"
                y_pos = self.y_offset + i * self.line_spacing
                draw_obj.text((5, y_pos), f"{arrow}{name}", font=self.font, fill=fill_color)

        self.display_manager.draw_custom(draw)
        self.logger.debug(f"DisplayMenu: Displayed items: {self.display_items}")

    # -------------------------------------------------------
    # Scrolling & Selection
    # -------------------------------------------------------
    def scroll_selection(self, direction):
        if not self.is_active:
            self.logger.warning("DisplayMenu: Attempted scroll while inactive.")
            return
        now = time.time()
        if now - self.last_action_time < self.debounce_interval:
            self.logger.debug("DisplayMenu: Scroll debounced.")
            return
        self.last_action_time = now

        old_index = self.current_index
        self.current_index += direction
        # Clamp to valid range
        self.current_index = max(0, min(self.current_index, len(self.display_items) - 1))

        if old_index != self.current_index:
            self.logger.debug(f"DisplayMenu: scrolled from {old_index} to {self.current_index}")
            self.show_items_list()

    def select_item(self):
        """
        A short press => select the item under highlight.
        """
        if not self.is_active:
            self.logger.warning("DisplayMenu: Attempted select while inactive.")
            return

        now = time.time()
        if now - self.last_action_time < self.debounce_interval:
            self.logger.debug("DisplayMenu: Select debounced.")
            return
        self.last_action_time = now

        selected_name = self.display_items[self.current_index]
        self.logger.info(f"DisplayMenu: Selected => {selected_name}")

        if not self.submenu_active:
            # ----- Normal top-level selection -----
            if selected_name == "Original":
                # Switch to 'original' playback mode
                self.logger.debug("DisplayMenu: Transition to classic screen.")
                self.mode_manager.config["display_mode"] = "original"
                self.mode_manager.set_display_mode("original")
                self.mode_manager.save_preferences()
                self.stop_mode()
                self.mode_manager.to_clock()

            if selected_name == "VU-Screen":
                # Switch to 'original' playback mode
                self.logger.debug("DisplayMenu: Transition to vumeterscreen.")
                self.mode_manager.config["display_mode"] = "vumeterscreen"
                self.mode_manager.set_display_mode("vumeterscreen")
                self.mode_manager.save_preferences()
                self.stop_mode()
                self.mode_manager.to_clock()

            elif selected_name == "Modern":
                # Instead of instantly switching,
                # open a sub-menu to let user pick spectrum on/off.
                self._open_modern_submenu()

            elif selected_name == "Brightness":
                self.logger.info("DisplayMenu: Opening Brightness sub-menu.")
                self._open_brightness_submenu()
                self.mode_manager.save_preferences()

            else:
                self.logger.warning(f"DisplayMenu: Unrecognized option: {selected_name}")

        else:
            # If we're in a sub-menu (e.g. brightness or modern-spectrum),
            # handle those selections
            if self.current_submenu_name == "brightness":
                self._handle_brightness_selection(selected_name)
                self.stop_mode()
                self.mode_manager.to_clock()

            elif self.current_submenu_name == "modern_spectrum":
                # The user is choosing "Spectrum: On" or "Spectrum: Off"
                self._handle_modern_spectrum_selection(selected_name)
                # Then we do the actual "modern" transition
                self.stop_mode()
                self.mode_manager.to_clock()

    # -------------------------------------------------------
    #  Modern Sub-Menu (Spectrum On/Off)
    # -------------------------------------------------------
    def _open_modern_submenu(self):
        """
        After picking 'Modern', ask the user if they want the spectrum
        (CAVA) On or Off. Then we set 'display_mode' to 'modern'
        plus set 'cava_enabled' (or your chosen config key).
        """
        # Save the current main list
        self.menu_stack.append((list(self.display_items), self.current_index))

        self.submenu_active = True
        self.current_submenu_name = "modern_spectrum"

        # We show two options: "Spectrum: Off" / "Spectrum: On"
        self.display_items = ["Spectrum: Off", "Spectrum: On"]
        self.current_index = 0
        self.show_items_list()

    def _handle_modern_spectrum_selection(self, selected_name):
        """
        If "Spectrum: On", set config["cava_enabled"] = True
        If "Spectrum: Off", set config["cava_enabled"] = False
        Also set 'display_mode' to 'modern'.
        """
        self.logger.debug(f"DisplayMenu: modern_spectrum => {selected_name}")
        # 1) Set display mode = modern
        self.mode_manager.config["display_mode"] = "modern"
        self.mode_manager.set_display_mode("modern")

        # 2) Turn CAVA / Spectrum on/off
        if selected_name == "Spectrum: On":
            self.mode_manager.config["cava_enabled"] = True
            self.logger.info("DisplayMenu: Spectrum enabled in modern mode.")
        else:
            self.mode_manager.config["cava_enabled"] = False
            self.logger.info("DisplayMenu: Spectrum disabled in modern mode.")

        # Save
        self.mode_manager.save_preferences()

        # Optionally re-start or stop the CAVA service here, or do it in the
        # modern screen's on_enter logic. For example:
        """
        import subprocess
        if self.mode_manager.config["cava_enabled"]:
            subprocess.run(["sudo", "systemctl", "start", "cava"])
        else:
            subprocess.run(["sudo", "systemctl", "stop", "cava"])
        """

        # Return to main list or exit
        self._close_submenu_and_return()

    # -------------------------------------------------------
    #  Brightness Sub-Menu
    # -------------------------------------------------------
    def _open_brightness_submenu(self):
        # Save current state
        self.menu_stack.append((list(self.display_items), self.current_index))
        self.submenu_active = True
        self.current_submenu_name = "brightness"

        # Now show 3 levels
        self.display_items = ["Low", "Medium", "High"]
        self.current_index = 0
        self.show_items_list()

    def _handle_brightness_selection(self, selected_level):
        """
        User picked "Low", "Medium", or "High". Apply contrast, then return.
        """
        self.logger.debug(f"DisplayMenu: Brightness sub-menu => {selected_level}")
        brightness_map = {
            "Low":    50,
            "Medium": 150,
            "High":   255
        }
        val = brightness_map.get(selected_level, 150)

        try:
            if hasattr(self.display_manager.oled, "contrast"):
                self.display_manager.oled.contrast(val)
                self.logger.info(f"DisplayMenu: Set brightness to {selected_level} => contrast({val}).")
            else:
                self.logger.warning("DisplayMenu: .contrast() not found on this display device.")
        except Exception as e:
            self.logger.error(f"DisplayMenu: Failed to set brightness => {e}")

        self.mode_manager.config["oled_brightness"] = val
        self.mode_manager.save_preferences()

        self._close_submenu_and_return()

    def _close_submenu_and_return(self):
        """
        Restore the old list items from the stack, or exit if none.
        """
        if self.menu_stack:
            old_items, old_index = self.menu_stack.pop()
            self.display_items  = old_items
            self.current_index  = old_index
            self.submenu_active = False
            self.current_submenu_name = None
            self.show_items_list()
        else:
            # no previous => just exit
            self.stop_mode()
            self.mode_manager.to_clock()
