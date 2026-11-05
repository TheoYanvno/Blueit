import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from blueit.cli import main
from blueit.library import Library
from blueit.project import credit, folder_for, intro, prepare, slug

from .test_series import story


class ProjectTest(unittest.TestCase):
    def test_slug_is_a_safe_folder_name(self):
        self.assertEqual(slug("I Found a Door in My Basement (Final)"), "i-found-a-door-in-my-basement-final")
        self.assertEqual(slug("../../etc/passwd"), "etc-passwd")
        self.assertEqual(slug("¿Qué pasó? 😱"), "que-paso")
        self.assertEqual(slug("!!!"), "story")
        self.assertLessEqual(len(slug("word " * 40)), 50)

    def test_intro_says_the_title_without_part_labels_and_credits_the_author(self):
        s = story("x1", "The Lighthouse Keeper (Final)", 10)
        self.assertEqual(intro(s), f"The Lighthouse Keeper. Written by {s.author}, on r/nosleep.")

    def test_credit_lists_the_author_link_and_every_part(self):
        s = story("x1", "Night Shift", 10)
        s = s.__class__(**{**s.__dict__, "parts": ("https://reddit.com/a", "https://reddit.com/b")})
        text = credit(s)
        self.assertIn(f'"Night Shift" by u/{s.author}', text)
        self.assertIn("  2. https://reddit.com/b", text)
        self.assertIn("Ask the author", text)

    def test_prepare_writes_the_script_and_credit(self):
        with tempfile.TemporaryDirectory() as d:
            s = story("ab12", "The Cabin", 10, body="**We** rented a [cabin](https://x.y).\n\nIt was dark.")
            folder = prepare(Path(d), s)
            self.assertEqual(folder, folder_for(Path(d), s))
            self.assertEqual(folder.name, "ab12-the-cabin")
            script = (folder / "script.txt").read_text(encoding="utf-8")
            self.assertTrue(script.startswith("The Cabin. Written by"))
            self.assertIn("We rented a cabin.\n\nIt was dark.", script)
            self.assertTrue((folder / "credit.txt").exists())


class NarrateCommandTest(unittest.TestCase):
    def run_cli(self, d, *argv):
        cfg = Path(d) / "blueit.toml"
        cfg.write_text(f'[blueit]\noutput = "{(Path(d) / "out").as_posix()}"\nvoice_engine = "silent"\n', encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--config", str(cfg), *argv, "--library", str(Path(d) / "library.db")])
        return code, out.getvalue(), err.getvalue()

    def test_narrate_next_reads_the_top_waiting_story_and_marks_it_narrated(self):
        with tempfile.TemporaryDirectory() as d:
            with Library(Path(d) / "library.db") as lib:
                lib.add(story("lo1", "A small one", 50, body="It was cold. " * 60))
                lib.add(story("hi1", "The big one", 900, body="The lights went out. " * 60))
            code, out, err = self.run_cli(d, "narrate", "--next")
            self.assertEqual(code, 0, err)
            self.assertIn("'The big one'", out)
            self.assertIn("with the silent voice", out)
            folder = Path(d) / "out" / "hi1-the-big-one"
            seg = json.loads((folder / "narration.json").read_text())["segments"]
            self.assertTrue(seg[0]["text"].startswith("The big one. Written by"))
            self.assertTrue((folder / "narration.wav").exists())
            with Library(Path(d) / "library.db") as lib:
                self.assertEqual(lib.get("hi1").status, "narrated")
                self.assertEqual(lib.get("lo1").status, "new")
            self.assertIn("'A small one'", self.run_cli(d, "narrate", "--next")[1])
            code, _, err = self.run_cli(d, "narrate", "--next")
            self.assertEqual(code, 1)
            self.assertIn("No story waiting", err)

    def test_narrate_by_id_and_unknown_ids(self):
        with tempfile.TemporaryDirectory() as d:
            with Library(Path(d) / "library.db") as lib:
                lib.add(story("id7", "Seven", 10, body="One line. " * 50))
            self.assertEqual(self.run_cli(d, "narrate", "id7")[0], 0)
            code, _, err = self.run_cli(d, "narrate", "nope")
            self.assertEqual(code, 1)
            self.assertIn("No story with id 'nope'", err)
            self.assertEqual(self.run_cli(d, "narrate")[0], 2)


if __name__ == "__main__":
    unittest.main()
