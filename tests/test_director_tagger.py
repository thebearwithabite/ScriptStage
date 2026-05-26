import unittest

from core.director.tagger import DirectorOptions, enhance_dialogue_line


class DirectorTaggerTests(unittest.TestCase):
    def test_adds_dramabox_tokens_and_audio_tags(self):
        line = "I can't believe you did that!"
        directed = enhance_dialogue_line(
            line,
            DirectorOptions(
                emotion="appalled",
                style="dramatic",
                voice="lead_female",
                tags_before=["sighs"],
            ),
        )
        self.assertEqual(
            directed,
            "{emotion=appalled} {style=dramatic} {voice=lead_female} [sighs] I can't believe you did that!",
        )

    def test_infers_default_tags_from_punctuation(self):
        self.assertEqual(
            enhance_dialogue_line("Are you serious?"),
            "[surprised] Are you serious?",
        )

    def test_filters_disallowed_non_voice_tags(self):
        directed = enhance_dialogue_line(
            "This is hard.",
            DirectorOptions(tags_before=["standing", "thoughtful", "music"]),
        )
        self.assertEqual(directed, "[thoughtful] This is hard.")


if __name__ == "__main__":
    unittest.main()
