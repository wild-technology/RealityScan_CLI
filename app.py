"""Launch the native ROVScan frontend with the existing project controller."""
import argparse
import sys


def main(argv=None, *, controller=None):
    parser = argparse.ArgumentParser(description="ROVScan desktop project workspace")
    parser.add_argument("project", nargs="?", help="Existing .rovscan document to open read-only")
    args = parser.parse_args(argv)
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtCore import QTimer
    from desktop.main_window import MainWindow
    from modules.project_workspace import ProjectDocument

    application = QApplication.instance() or QApplication(sys.argv[:1])
    application.setApplicationName("ROVScan")
    application.setOrganizationName("Wild Technology")
    if controller is None:
        try:
            from modules.project_controller import ProjectController
        except ModuleNotFoundError as exc:
            QMessageBox.critical(None, "Installation incomplete",
                                 f"The production project controller could not be loaded: {exc}\n"
                                 "Run deployment preflight and repair the installation before starting the desktop app.")
            return 2
        else:
            controller = ProjectController()
    project = None
    if args.project:
        try:
            project = ProjectDocument.load(args.project)
        except (ValueError, OSError) as exc:
            QMessageBox.critical(None, "Cannot open project", str(exc))
            return 2
    window = MainWindow(controller=controller, project=project)
    window.show()
    QTimer.singleShot(0, window.show_setup)
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
