"""
Tests for the submit_feedback API endpoint's rating validation.

Covers the string-coercion fix: JSON string ratings ("4") must be saved,
non-coercible or out-of-range values must be rejected with 400 — previously
both were silently saved as None while still returning success.
"""

import json

from django.test import TestCase
from django.urls import reverse

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
