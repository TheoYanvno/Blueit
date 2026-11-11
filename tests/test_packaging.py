import sys
import unittest
from unittest import mock

from blueit import cli


class PackagedApp(unittest.TestCase):
    """Double-clicking Blueit.exe (no arguments, running frozen) opens the page."""

    def test_no_arguments_in_the_packaged_app_runs_ui(self):
        with mock.patch.object(sys, "frozen", True, create=True), \
             mock.patch.object(cli, "cmd_ui", return_value=0) as ui:
            self.assertEqual(cli.main([]), 0)
        ui.assert_called_once()

    def test_from_python_a_command_is_still_required(self):
        with self.assertRaises(SystemExit):
            cli.main([])

    def test_the_static_page_is_found_next_to_the_code(self):
        from blueit.web import STATIC
        self.assertTrue((STATIC / "index.html").is_file())


if __name__ == "__main__":
    unittest.main()
