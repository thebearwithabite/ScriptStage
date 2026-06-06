import unittest
from core.caster.characters import normalize_character_name

class TestCasterCharacters(unittest.TestCase):
    def test_normalize_standard_name(self):
        self.assertEqual(normalize_character_name("JOHN"), "JOHN")
        self.assertEqual(normalize_character_name("Jane Doe"), "JANE DOE")

    def test_normalize_lowercase(self):
        self.assertEqual(normalize_character_name("john"), "JOHN")
        self.assertEqual(normalize_character_name("jane doe"), "JANE DOE")

    def test_normalize_standard_extensions(self):
        self.assertEqual(normalize_character_name("JOHN (V.O.)"), "JOHN")
        self.assertEqual(normalize_character_name("JOHN (O.S.)"), "JOHN")
        self.assertEqual(normalize_character_name("JOHN (CONT'D)"), "JOHN")
        self.assertEqual(normalize_character_name("JOHN (O.C.)"), "JOHN")

    def test_normalize_custom_parentheticals(self):
        self.assertEqual(normalize_character_name("JOHN (AS A CHILD)"), "JOHN")
        self.assertEqual(normalize_character_name("GIRL (LATER)"), "GIRL")
        self.assertEqual(normalize_character_name("MAN (IN DISTANCE)"), "MAN")

    def test_normalize_multiple_parentheticals(self):
        self.assertEqual(normalize_character_name("JOHN (O.S.) (CONT'D)"), "JOHN")
        self.assertEqual(normalize_character_name("JOHN (V.O.) (CONT'D)"), "JOHN")

    def test_normalize_whitespace(self):
        self.assertEqual(normalize_character_name("  JOHN  "), "JOHN")
        self.assertEqual(normalize_character_name("\tJOHN\n"), "JOHN")

    def test_normalize_internal_spaces(self):
        self.assertEqual(normalize_character_name("JOHN    DOE"), "JOHN DOE")
        self.assertEqual(normalize_character_name("DR.    SMITH"), "DR. SMITH")

    def test_normalize_trailing_colon(self):
        self.assertEqual(normalize_character_name("JOHN:"), "JOHN")
        self.assertEqual(normalize_character_name("DR. SMITH :"), "DR. SMITH")

    def test_normalize_complex_case(self):
        self.assertEqual(normalize_character_name("  dr. smith (o.s.) :  "), "DR. SMITH")
        self.assertEqual(normalize_character_name("  SARAH (1950s) (CONT'D)  "), "SARAH")

if __name__ == "__main__":
    unittest.main()
