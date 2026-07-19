"""
Tests for the submit_feedback API endpoint's rating validation.

Covers the string-coercion fix: JSON string ratings ("4") must be saved,
non-coercible or out-of-range values must be rejected with 400 — previously
both were silently saved as None while still returning success.
"""

import json

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from resume.api_views import _coerce_rating
from resume.models import Feedback


class SubmitFeedbackRatingTests(TestCase):
    def _post(self, payload):
        return self.client.post(
            reverse("feedback"), json.dumps(payload), content_type="application/json"
        )

    def _post_rating(self, rating):
        # message/page stay valid non-null throughout: nulling them hits an
        # unrelated pre-existing 500 path that would mask rating results.
        return self._post(
            {"message": "Great tool!", "rating": rating, "page": "/dashboard/"}
        )

    def test_string_rating_is_coerced_to_int(self):
        # The reported bug: "4" was silently saved as rating=None.
        resp = self._post_rating("4")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Feedback.objects.get().rating, 4)

    def test_bounds_accepted_as_int_and_string(self):
        for value in (1, 5, "1", "5"):
            with self.subTest(value=value):
                resp = self._post_rating(value)
                self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            sorted(Feedback.objects.values_list("rating", flat=True)), [1, 1, 5, 5]
        )

    def test_whole_float_is_coerced_to_int(self):
        resp = self._post_rating(4.0)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Feedback.objects.get().rating, 4)

    def test_missing_or_null_rating_saves_none(self):
        for payload in (
            {"message": "no rating given", "page": "/"},
            {"message": "explicit null", "rating": None, "page": "/"},
        ):
            with self.subTest(payload=payload):
                resp = self._post(payload)
                self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            list(Feedback.objects.values_list("rating", flat=True)), [None, None]
        )

    def test_invalid_ratings_rejected_with_400_and_no_row(self):
        invalid = ["abc", "", "4.0", 4.5, True, False, [1, 2], {"a": 1}, 0, 6, "99", 6.0]
        for value in invalid:
            with self.subTest(value=value):
                resp = self._post_rating(value)
                self.assertEqual(resp.status_code, 400)
                self.assertIn("error", resp.json())
        self.assertEqual(Feedback.objects.count(), 0)

    def test_message_still_required(self):
        resp = self._post({"message": "", "rating": 4, "page": "/"})
        self.assertEqual(resp.status_code, 400)

    def test_negative_rating_rejected_with_400_and_no_row(self):
        for value in (-1, "-1", -5.0):
            with self.subTest(value=value):
                resp = self._post_rating(value)
                self.assertEqual(resp.status_code, 400)
        self.assertEqual(Feedback.objects.count(), 0)


class CoerceRatingUnitTests(SimpleTestCase):
    """Direct unit tests for the _coerce_rating() helper (resume/api_views.py)."""

    def test_none_returns_none(self):
        self.assertIsNone(_coerce_rating(None))

    def test_valid_ints_returned_unchanged(self):
        for value in range(1, 6):
            with self.subTest(value=value):
                self.assertEqual(_coerce_rating(value), value)

    def test_numeric_string_is_coerced_to_int(self):
        self.assertEqual(_coerce_rating("3"), 3)

    def test_whole_number_float_is_coerced_to_int(self):
        self.assertEqual(_coerce_rating(2.0), 2)

    def test_string_with_surrounding_whitespace_is_coerced(self):
        # int() strips ASCII whitespace, so " 4 " coerces just like "4".
        self.assertEqual(_coerce_rating(" 4 "), 4)

    def test_bool_is_rejected_despite_being_int_subclass(self):
        for value in (True, False):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    _coerce_rating(value)

    def test_non_integer_float_is_rejected(self):
        with self.assertRaises(ValueError):
            _coerce_rating(4.5)

    def test_out_of_range_values_are_rejected(self):
        for value in (0, 6, -1, 100, "-1", "0", "6"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    _coerce_rating(value)

    def test_non_coercible_string_is_rejected(self):
        for value in ("abc", "", "4.0", "4,0", " "):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    _coerce_rating(value)

    def test_non_numeric_types_are_rejected(self):
        for value in ([1, 2], {"a": 1}, object()):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    _coerce_rating(value)
