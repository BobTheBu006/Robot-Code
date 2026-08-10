"""Reading the condition strings on If / While blocks.

A condition arrives from a workflow file, which is data - hand-edited, copied
between machines, possibly written by someone else. On a machine wired to
motors, "open this workflow" must never mean "run this code", so the refusal
tests below matter as much as the ones that compute an answer.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine.conditions import ConditionError, evaluate_condition


def _context(**overrides):
    context = {
        "$in": {"temperature": 45, "name": "left", "aborted": False, "volume_ml": 2.5},
        "$blocks": {"calibrate_z": {"calibrated": True, "travel_cm": 60.0}},
        "$run": {"iteration": 2},
    }
    context.update(overrides)
    return context


class ComparisonTests(unittest.TestCase):
    def test_a_numeric_comparison_decides_the_branch(self) -> None:
        self.assertTrue(evaluate_condition("$in.temperature > 40", _context()).value)
        self.assertFalse(evaluate_condition("$in.temperature > 100", _context()).value)

    def test_a_nested_block_result_can_be_read(self) -> None:
        self.assertTrue(evaluate_condition("$blocks.calibrate_z.calibrated == true", _context()).value)

    def test_strings_compare(self) -> None:
        self.assertTrue(evaluate_condition('$in.name == "left"', _context()).value)
        self.assertFalse(evaluate_condition('$in.name == "right"', _context()).value)

    def test_chained_comparison(self) -> None:
        self.assertTrue(evaluate_condition("40 < $in.temperature < 50", _context()).value)

    def test_membership(self) -> None:
        self.assertTrue(evaluate_condition('$in.name in ["left", "right"]', _context()).value)

    def test_arithmetic_inside_a_comparison(self) -> None:
        self.assertTrue(evaluate_condition("$in.volume_ml * 2 >= 5", _context()).value)


class BooleanLogicTests(unittest.TestCase):
    def test_and_or_not(self) -> None:
        self.assertTrue(evaluate_condition("$in.volume_ml >= 1 and not $in.aborted", _context()).value)
        self.assertFalse(evaluate_condition("$in.aborted and $in.temperature > 0", _context()).value)
        self.assertTrue(evaluate_condition("$in.aborted or $in.temperature > 0", _context()).value)

    def test_loop_iteration_is_visible(self) -> None:
        self.assertTrue(evaluate_condition("$run.iteration < 5", _context()).value)
        self.assertFalse(evaluate_condition("$run.iteration < 2", _context()).value)


class SpellingTests(unittest.TestCase):
    def test_javascript_style_literals_are_accepted(self) -> None:
        # The blocks came from an n8n-shaped world; authors write `true`.
        self.assertTrue(evaluate_condition("true", _context()).value)
        self.assertFalse(evaluate_condition("false", _context()).value)

    def test_template_braces_are_stripped(self) -> None:
        self.assertTrue(evaluate_condition("{{ $in.temperature > 40 }}", _context()).value)

    def test_a_dollar_inside_a_string_is_left_alone(self) -> None:
        self.assertTrue(evaluate_condition('"$in" == "$in"', _context()).value)


class EmptyConditionTests(unittest.TestCase):
    def test_an_empty_condition_is_false_not_a_crash_and_not_true(self) -> None:
        # False is the safe reading: it ends a while loop rather than spinning
        # forever, and takes the false branch rather than guessing.
        for blank in ("", "   ", None, "{{ }}"):
            result = evaluate_condition(blank, _context())
            self.assertFalse(result.value)
            self.assertIn("no condition", result.detail.lower())


class RefusalTests(unittest.TestCase):
    def test_function_calls_are_refused(self) -> None:
        with self.assertRaises(ConditionError) as caught:
            evaluate_condition('__import__("os").system("ls")', _context())
        self.assertIn("Call", str(caught.exception))

    def test_opening_a_file_is_refused(self) -> None:
        with self.assertRaises(ConditionError):
            evaluate_condition('open("/etc/passwd").read()', _context())

    def test_comprehensions_are_refused(self) -> None:
        with self.assertRaises(ConditionError):
            evaluate_condition("[x for x in range(3)]", _context())

    def test_assignment_is_refused(self) -> None:
        with self.assertRaises(ConditionError):
            evaluate_condition("$in.temperature := 5", _context())

    def test_a_missing_field_is_named_rather_than_treated_as_false(self) -> None:
        with self.assertRaises(ConditionError) as caught:
            evaluate_condition("$in.missing > 1", _context())
        message = str(caught.exception)
        self.assertIn("missing", message)
        self.assertIn("temperature", message, "the message should say what was available instead")

    def test_nonsense_is_refused_with_a_readable_message(self) -> None:
        with self.assertRaises(ConditionError) as caught:
            evaluate_condition("$in.temperature >", _context())
        self.assertIn("not a condition", str(caught.exception))

    def test_divide_by_zero_is_reported(self) -> None:
        with self.assertRaises(ConditionError) as caught:
            evaluate_condition("1 / 0 > 1", _context())
        self.assertIn("zero", str(caught.exception))

    def test_comparing_incompatible_types_is_reported(self) -> None:
        with self.assertRaises(ConditionError) as caught:
            evaluate_condition('$in.temperature > "hot"', _context())
        self.assertIn("compares", str(caught.exception))


class ReportingTests(unittest.TestCase):
    def test_the_result_explains_itself(self) -> None:
        result = evaluate_condition("$in.temperature > 40", _context())
        self.assertEqual(result.expression, "$in.temperature > 40")
        self.assertIn("True", result.detail)


if __name__ == "__main__":
    unittest.main()
