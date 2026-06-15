import unittest
from core.models import Character, CharacterStats
from core.caster.scoring import compute_prominence

class TestScoring(unittest.TestCase):
    def test_empty_input(self):
        # Empty characters list
        self.assertEqual(compute_prominence([], 10), {})
        # Zero total scenes
        self.assertEqual(compute_prominence([Character(name="ALICE")], 0), {})

    def test_single_character(self):
        char = Character(
            name="ALICE",
            stats=CharacterStats(lines=10, words=100),
            scenes_list=[1, 2, 3],
            first_scene=1,
            last_scene=3
        )
        scores = compute_prominence([char], 3)
        self.assertEqual(scores, {"ALICE": 1.0})

    def test_normalization(self):
        char1 = Character(
            name="LEAD",
            stats=CharacterStats(lines=100, words=1000),
            scenes_list=list(range(1, 11)),
            first_scene=1,
            last_scene=10
        )
        char2 = Character(
            name="SUPPORT",
            stats=CharacterStats(lines=10, words=100),
            scenes_list=[5],
            first_scene=5,
            last_scene=5
        )
        scores = compute_prominence([char1, char2], 10)
        self.assertEqual(scores["LEAD"], 1.0)
        self.assertLess(scores["SUPPORT"], 1.0)
        self.assertGreater(scores["SUPPORT"], 0)

    def test_act_presence(self):
        # Total scenes = 100.
        # Act 1: 1-25, Act 2: 26-75, Act 3: 76-100

        # Char 1: In all 3 acts
        char1 = Character(
            name="EVERYWHERE",
            stats=CharacterStats(lines=10, words=100),
            scenes_list=[1, 50, 90],
            first_scene=1,
            last_scene=90
        )
        # Char 2: Only in Act 1, same stats
        char2 = Character(
            name="ACT1_ONLY",
            stats=CharacterStats(lines=10, words=100),
            scenes_list=[1, 2, 3],
            first_scene=1,
            last_scene=3
        )

        scores = compute_prominence([char1, char2], 100)
        # EVERYWHERE should have higher prominence due to arc_spread and act_presence
        self.assertEqual(scores["EVERYWHERE"], 1.0)
        self.assertLess(scores["ACT1_ONLY"], 1.0)

    def test_zero_stats_character(self):
        # Character present in scenes but has 0 words/lines
        char = Character(
            name="SILENT",
            stats=CharacterStats(lines=0, words=0),
            scenes_list=[1, 2],
            first_scene=1,
            last_scene=2
        )
        scores = compute_prominence([char], 10)
        self.assertEqual(scores, {"SILENT": 1.0})

    def test_density_maxing(self):
        # Density is (words/lines)/20.0, max 1.0.
        # Char 1: 40 words/line -> density 1.0
        char1 = Character(
            name="WORDY",
            stats=CharacterStats(lines=1, words=40),
            scenes_list=[1],
            first_scene=1,
            last_scene=1
        )
        # Char 2: 10 words/line -> density 0.5
        char2 = Character(
            name="BRIEF",
            stats=CharacterStats(lines=1, words=10),
            scenes_list=[1],
            first_scene=1,
            last_scene=1
        )
        scores = compute_prominence([char1, char2], 1)
        self.assertEqual(scores["WORDY"], 1.0)
        self.assertLess(scores["BRIEF"], 1.0)

if __name__ == "__main__":
    unittest.main()
