import sys
import logging
import subprocess
import webbrowser
import os
from pathlib import Path
from PySide6.QtCore import QTimer, QDir, QCoreApplication, QObject, QEvent, QPoint
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QWidget
from PySide6.QtGui import QIcon, QAction
from .util import retrieve_settings, add_settings, user_status, idletime_settings, launchon_start, signout, cached_credentials
from .manager import Manager
import sys
logger = logging.getLogger(__name__)

manager = Manager()


# Function to open URLs
def open_url(url: str) -> None:
    try:
        if sys.platform == "linux":
            subprocess.Popen(["xdg-open", url])
        else:
            webbrowser.open(url)
    except Exception as e:
        logger.error(f"Failed to open URL {url}: {e}")


# def open_webui(root_url: str) -> None:
#     """Open the web dashboard."""
#     open_url(root_url)


def open_dir(d: str) -> None:
    """Open a directory in the system's default file manager."""
    try:
        if sys.platform == "win32":
            os.startfile(d)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", d])
        else:
            subprocess.Popen(["xdg-open", d])
    except Exception as e:
        logger.error(f"Failed to open directory {d}: {e}")


class TrayIcon(QSystemTrayIcon):
    def __init__(self, icon: QIcon, parent: QWidget = None):
        super().__init__(icon, parent)
        self._parent = parent
        self.root_url = "http://localhost:7600"
        self.root_schedule = "http://localhost:7600/pages/settings"

        # Initialize flag
        self.is_logged_in = False

        # Initialize user status and credentials
        self.user_status = user_status()
        self.previous_status = self.user_status
        self.credentials = cached_credentials().json()

        # Set the flag based on credentials
        self.check_login_status()

        # Connect signals and setup menu
        self.activated.connect(self.on_activated)
        self.update_menu()

        # Timer for periodic user status checks
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.check_user_status)
        self.status_timer.start(60000)  # Every 60 seconds

        # Install a global event filter for outside clicks
        self.event_filter = TrayEventFilter(self)
        QApplication.instance().installEventFilter(self.event_filter)

    def check_login_status(self):
        """Check if the user is logged in and set the flag."""
        self.is_logged_in = bool(self.credentials and self.credentials.get("userId"))

    def update_menu(self):
        """Rebuild the tray menu based on the current login status."""
        menu = QMenu(self._parent)
        if self.is_logged_in:
            # Show menu items for logged-in users
            self.settings = retrieve_settings()

            # Launch on Start action
            launch_action = QAction("Launch on Start", self)
            launch_action.setCheckable(True)
            launch_action.setChecked(self.settings.get("launch", False))
            launch_action.triggered.connect(self.toggle_launch_on_start)
            menu.addAction(launch_action)

            # Enable Idle Time action
            idle_time_action = QAction("Enable Idle Time", self)
            idle_time_action.setCheckable(True)
            idle_time_action.setChecked(self.settings.get("idle_time", False))
            idle_time_action.triggered.connect(self.toggle_idle_time)
            menu.addAction(idle_time_action)

            # Schedule Menu action
            schedule_menu = QAction("Schedule", self)
            schedule_menu.triggered.connect(lambda: self.open_webui(self.root_schedule))
            menu.addAction(schedule_menu)
            menu.addSeparator()

            # Sign Out action
            signout_action = QAction("Sign Out", self)
            signout_action.triggered.connect(self.sign_out)
            menu.addAction(signout_action)
        else:
            # Show "Login" menu item if not logged in
            login_action = QAction("Login", self)
            login_action.triggered.connect(lambda: self.open_webui(self.root_url))
            menu.addAction(login_action)

        # Quit option
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.quit_application)
        menu.addAction(quit_action)

        self.setContextMenu(menu)

    def open_webui(self, root_url: str) -> None:
        """Open the web dashboard."""
        open_url(root_url)
        self.is_logged_in = True
        self.update_menu()

    def sign_out(self):
        """Sign out the user, reset the flag, and update the menu."""
        try:
            signout()
            self.is_logged_in = False  # Reset flag
            manager.stop_all_watchers()
            self.update_menu()  # Update menu immediately
        except Exception as e:
            logger.error(f"Failed to sign out: {e}")

    def check_user_status(self):
        """Check if the user status has changed and rebuild the menu if needed."""
        try:
            current_status = user_status()
            if current_status != self.previous_status:
                self.previous_status = current_status
                self.credentials = cached_credentials().json()
                self.check_login_status()  # Update the login flag
                self.update_menu()  # Rebuild the menu
        except Exception as e:
            logger.error(f"Error checking user status: {e}")

    def toggle_launch_on_start(self):
        """Toggle the 'Launch on Start' setting."""
        try:
            launch_on_start = not self.settings.get("launch", False)
            launchon_start(launch_on_start)
            self.settings["launch"] = launch_on_start
            self.update_menu()
        except Exception as e:
            logger.error(f"Failed to toggle Launch on Start: {e}")

    def toggle_idle_time(self):
        """Toggle the 'Idle Time' setting."""
        try:
            idle_time = not self.settings.get("idle_time", False)
            self.settings["idle_time"] = idle_time
            idletime_settings()
            self.update_menu()
        except Exception as e:
            logger.error(f"Failed to toggle Idle Time: {e}")

    def on_activated(self, reason: QSystemTrayIcon.ActivationReason):
        """Handle tray icon activation."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.update_menu()
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_webui(self.root_url)

    def quit_application(self):
        """Quit the application."""
        try:
            manager.stop_all()
        except Exception as e:
            logger.error(f"Error stopping watchers: {e}")
        QApplication.quit()
        sys.exit(0)

class TrayEventFilter(QObject):
    """Event filter to close the tray menu when clicking outside."""
    def __init__(self, tray_icon):
        super().__init__()
        self.tray_icon = tray_icon

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress:
            menu = self.tray_icon.contextMenu()
            if menu and not menu.geometry().contains(event.globalPosition().toPoint()):
                menu.hide()
        return super().eventFilter(obj, event)

def run() -> int:
    """Initialize and run the PySide6 application."""
    app = QApplication(sys.argv)
    scriptdir = Path(__file__).parent

    # Add search paths for icon resources
    QDir.addSearchPath("icons", str(scriptdir.parent / "media/logo/"))
    QDir.addSearchPath("icons", str(scriptdir.parent.parent / "Resources/sd_qt/media/logo/"))

    # Set up the tray icon
    icon_path = "icons:black-monochrome-logo.png" if sys.platform == "darwin" else "icons:logo.png"
    icon = QIcon(icon_path)

    if icon.isNull():
        logger.error("Failed to load tray icon.")
        return -1

    # Create the tray icon
    tray_icon = TrayIcon(icon)

    # Define a slot to handle single clicks
    def on_tray_icon_activated(reason):
        if reason == QSystemTrayIcon.Trigger:  # Single click
            logger.info("Tray icon single-clicked.")
            # Add your desired behavior here, e.g., showing a menu or window
            tray_icon.showMessage("Tray Icon", "You single-clicked the tray icon!")

    # Connect the activated signal
    tray_icon.activated.connect(on_tray_icon_activated)

    tray_icon.show()
    QApplication.setQuitOnLastWindowClosed(False)
    return app.exec()


if __name__ == "__main__":
    run()