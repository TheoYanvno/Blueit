import unittest

from blueit.clean import clean


class Clean(unittest.TestCase):
    def test_markdown_and_links(self):
        text = "**Bold** and _soft_ with a [link](https://x.com) and https://y.com\n\n> quoted\n\n---\n\n# Heading"
        self.assertEqual(clean(text), "Bold and soft with a link and\n\nquoted\n\nHeading")

    def test_edits_at_the_end_are_dropped(self):
        story = "\n\n".join(["Paragraph of story."] * 10) + "\n\nEDIT: thanks for the gold!"
        self.assertNotIn("gold", clean(story))
        self.assertIn("gold", clean(story, keep_edits=True))

    def test_edit_near_the_start_is_kept(self):
        story = "EDIT: fixed a typo\n\n" + "\n\n".join(["Paragraph of story."] * 10)
        self.assertIn("typo", clean(story))

    def test_shorthand_and_ages(self):
        self.assertEqual(clean("My MIL (58F) called IRL &amp; laughed"),
                         "My mother-in-law, a 58-year-old woman, called in real life & laughed")
        self.assertEqual(clean("I was SO scared"), "I was SO scared")

    def test_spoilers_and_whitespace(self):
        self.assertEqual(clean("It was >!the neighbor!<.\r\n\r\n\r\n  Done.  "), "It was the neighbor.\n\nDone.")


if __name__ == "__main__":
    unittest.main()
