#!/usr/bin/env python3
# src/main.py

import RPi.GPIO as GPIO
GPIO.setwarnings(False)
import time
import threading
import logging
import yaml
import os
import sys
from PIL import Image, ImageSequence

from display.screens.clock import Clock
from hardware.buttonsleds import ButtonsLEDController
from display.screens.original_screen import OriginalScreen
from display.screens.modern_screen import ModernScreen
from display.screens.system_info_screen import SystemInfoScreen
from display.screensavers.snake_screensaver import SnakeScreensaver
from display.screensavers.starfield_screensaver import StarfieldScreensaver
from display.screensavers.bouncing_text_screensaver import BouncingTextScreensaver
from display.display_manager import DisplayManager
from display.screens.clock import Clock
from managers.menu_manager import MenuManager
from managers.mode_manager import ModeManager
from managers.manager_factory import ManagerFactory
from controls.rotary_control import RotaryControl
from hardware.buttonsleds import ButtonsLEDController
from network.volumio_listener import VolumioListener

def load_config(config_path='/config.yaml'):
    abs_path = os.path.abspath(config_path)
    print(f"Attempting to load config from: {abs_path}")
    print(f"Does the file exist? {os.path.isfile(config_path)}")  # Debug line
    config = {}
    if os.path.isfile(config_path):
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f) or {}
            logging.debug(f"Configuration loaded from {config_path}.")
        except yaml.YAMLError as e:
            logging.error(f"Error loading config file {config_path}: {e}")
    else:
        logging.warning(f"Config file {config_path} not found. Using default configuration.")
    return config

def main():
    # 1) Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    logger = logging.getLogger("Main")

    # 2) Load configuration
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, '..', 'config.yaml')
    config = load_config(config_path)

    # 3) Initialize DisplayManager
    display_config = config.get('display', {})
    display_manager = DisplayManager(display_config)

    # 4) Display a startup logo for 5 seconds
    logger.info("Displaying startup logo...")
    display_manager.show_logo()
    logger.info("Startup logo displayed for 5 seconds.")
    time.sleep(5)
    display_manager.clear_screen()
    logger.info("Screen cleared after logo display.")

    # 5) Setup readiness events
    volumio_ready_event = threading.Event()
    min_loading_event = threading.Event()
    MIN_LOADING_DURATION = 5  # seconds

    def set_min_loading_event():
        time.sleep(MIN_LOADING_DURATION)
        min_loading_event.set()
        logger.info("Minimum loading duration has elapsed.")

    threading.Thread(target=set_min_loading_event, daemon=True).start()

    def show_loading():
        loading_gif_path = display_config.get('loading_gif_path', 'loading.gif')
        try:
            image = Image.open(loading_gif_path)
            if not getattr(image, "is_animated", False):
                logger.warning(f"Loading GIF '{loading_gif_path}' is not animated.")
                return
        except IOError:
            logger.error(f"Failed to load loading GIF '{loading_gif_path}'.")
            return

        logger.info("Displaying loading GIF during startup.")
        display_manager.clear_screen()
        time.sleep(0.1)

        while not (volumio_ready_event.is_set() and min_loading_event.is_set()):
            for frame in ImageSequence.Iterator(image):
                if volumio_ready_event.is_set() and min_loading_event.is_set():
                    logger.info("Volumio ready & min load done, stopping loading GIF.")
                    return
                display_manager.oled.display(frame.convert(display_manager.oled.mode))
                frame_duration = frame.info.get('duration', 100) / 1000.0
                time.sleep(frame_duration)

        logger.info("Exiting loading GIF display thread.")

    threading.Thread(target=show_loading, daemon=True).start()

    # 6) Initialize VolumioListener
    volumio_cfg = config.get('volumio', {})
    volumio_host = volumio_cfg.get('host', 'localhost')
    volumio_port = volumio_cfg.get('port', 3000)
    volumio_listener = VolumioListener(host=volumio_host, port=volumio_port)

    def on_state_changed(sender, state):
        logger.info(f"Volumio state changed: {state}")
        if state.get('status') in ['play', 'stop', 'pause', 'unknown']:
            logger.info("Volumio is considered ready now.")
            volumio_ready_event.set()
            # Optionally disconnect the callback
            volumio_listener.state_changed.disconnect(on_state_changed)

    volumio_listener.state_changed.connect(on_state_changed)

    # 7) Wait for both events
    logger.info("Waiting for Volumio readiness & min load time.")
    volumio_ready_event.wait()
    min_loading_event.wait()
    logger.info("Volumio is ready & min loading time passed, proceeding...")

    # 8) Initialize Clock
    clock_config = config.get('clock', {})
    clock = Clock(display_manager, clock_config)
    clock.logger = logging.getLogger("Clock")
    clock.logger.setLevel(logging.INFO)

    # 9) Initialize ModeManager (Quadify style)
    mode_manager = ModeManager(
        display_manager   = display_manager,
        clock             = clock,
        volumio_listener  = volumio_listener,
        preference_file_path="../preference.json",  # or your chosen path
        config            = config
    )

    # 10) Create ManagerFactory & set up managers/screens
    manager_factory = ManagerFactory(
        display_manager   = display_manager,
        volumio_listener  = volumio_listener,
        mode_manager      = mode_manager,
        config            = config
    )
    manager_factory.setup_mode_manager()


    # Similarly for clock_menu, display_menu, system_info_screen, screensaver_menu, screensaver
    # if you want direct references. Or you can just rely on mode_manager.* if it’s set.

    # 11) Assign the ModeManager to volumio_listener
    volumio_listener.mode_manager = mode_manager

    mode_manager.to_clock()
    logger.info("Forced system into 'clock' mode after all initialization.")

    # 12) ButtonsLEDs
    #buttons_leds = ButtonsLEDController(config_path=config_path)
    #buttons_leds.start()

    # 13) Define RotaryControl callbacks
    def on_rotate(direction):
        current_mode = mode_manager.get_mode()

        # For Original + Modern => adjust volume
        
        if current_mode == 'original':
            volume_change = 40 if direction == 1 else -40
            mode_manager.original_screen.adjust_volume(volume_change)

        elif current_mode == 'modern':
            volume_change = 10 if direction == 1 else -20
            mode_manager.modern_screen.adjust_volume(volume_change)
            logger.debug(f"ModernScreen: Adjusted volume by {volume_change}")

        elif current_mode == 'webradio':
            volume_change = 10 if direction == 1 else -20
            mode_manager.webradio_screen.adjust_volume(volume_change)
            logger.debug(f"WebRadioScreen: Adjusted volume by {volume_change}")

        elif current_mode == 'menu':
            mode_manager.menu_manager.scroll_selection(direction)
            logger.debug(f"Scrolled menu with direction: {direction}")

        elif current_mode == 'configmenu':
            mode_manager.config_menu.scroll_selection(direction)

        # If we're in screensaver mode, exit on any rotation
        elif current_mode == 'screensaver':
            mode_manager.exit_screensaver()

        elif current_mode == 'clockmenu':
            mode_manager.clock_menu.scroll_selection(direction)

        elif current_mode == 'screensavermenu':
            mode_manager.screensaver_menu.scroll_selection(direction)

        elif current_mode == 'displaymenu':
            mode_manager.display_menu.scroll_selection(direction)

        elif current_mode == 'tidal':
            mode_manager.tidal_manager.scroll_selection(direction)

        elif current_mode == 'qobuz':
            mode_manager.qobuz_manager.scroll_selection(direction)

        elif current_mode == 'spotify':
            mode_manager.spotify_manager.scroll_selection(direction)

        elif current_mode == 'playlists':
            mode_manager.playlist_manager.scroll_selection(direction)

        elif current_mode == 'radiomanager':
            mode_manager.radio_manager.scroll_selection(direction)

        elif current_mode == 'library':
            mode_manager.library_manager.scroll_selection(direction)

        elif current_mode == 'usblibrary':
            mode_manager.usb_library_manager.scroll_selection(direction)
        else:
            logger.warning(f"Unhandled mode: {current_mode}; no rotary action performed.")



    def on_button_press_inner():
        current_mode = mode_manager.get_mode()

        if current_mode == 'clock':
            mode_manager.to_menu()

        elif current_mode == 'menu':
            mode_manager.menu_manager.select_item()

        elif current_mode == 'configmenu':
            mode_manager.config_menu.select_item()

        elif current_mode == 'screensavermenu':
            mode_manager.screensaver_menu.select_item()

        elif current_mode == 'displaymenu':
            mode_manager.display_menu.select_item()

        elif current_mode == 'clockmenu':
            mode_manager.clock_menu.select_item()

        elif current_mode in ['original', 'modern']:
            # Toggle play/pause in original or modern mode
            logger.info(f"Button pressed in {current_mode} mode; toggling playback.")
            screen = mode_manager.original_screen if current_mode == 'original' else mode_manager.modern_screen
            if screen:
                screen.toggle_play_pause()
            else:
                logger.warning(f"No screen instance found for mode: {current_mode}")

        elif current_mode == 'playlists':
            mode_manager.playlist_manager.select_item()

        elif current_mode == 'tidal':
            mode_manager.tidal_manager.select_item()

        elif current_mode == 'qobuz':
            mode_manager.mode_manager.qobuz_manager.select_item()

        elif current_mode == 'spotify':
            mode_manager.spotify_manager.select_item()

        elif current_mode == 'webradio':
            mode_manager.radio_manager.select_item()

        elif current_mode == 'library':
            mode_manager.library_manager.select_item()

        elif current_mode == 'radiomanager':
            mode_manager.radio_manager.select_item()

        elif current_mode == 'usblibrary':
            mode_manager.usb_library_manager.select_item()

        elif current_mode == 'screensaver':
            # Pressing button in screensaver => exit screensaver
            mode_manager.exit_screensaver()

        else:
            logger.warning(f"Unhandled mode: {current_mode}; no button action performed.")

    def on_long_press():
        logger.info("Long button press detected.")
        current_mode = mode_manager.get_mode()
        # Example: go back to clock if not already
        if current_mode != 'clock':
            mode_manager.to_clock()

    # 14) Initialize RotaryControl
    rotary_control = RotaryControl(
        rotation_callback     = on_rotate,
        button_callback       = on_button_press_inner,
        long_press_callback   = on_long_press,
        long_press_threshold  = 2.5
    )
    rotary_control.start()

    # 15) Main application loop
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down Quadify via KeyboardInterrupt.")
    finally:
        buttons_leds.stop()
        rotary_control.stop()
        volumio_listener.stop_listener()
        clock.stop()
        display_manager.clear_screen()
        logger.info("Quadify shut down gracefully.")

if __name__ == "__main__":
    main()
