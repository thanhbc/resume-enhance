"""
Resume API Views using Django REST Framework.

These ViewSets provide CRUD operations for Resume model
via REST API endpoints for mobile and frontend apps.
"""

import json
import logging

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Resume, Feedback
from .serializers import (
    ResumeListSerializer,
    ResumeDetailSerializer,
    ResumeCreateSerializer,
)


logger = logging.getLogger(__name__)


class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Custom permission to only allow owners of a resume to edit it.
    """

    def has_object_permission(self, request, view, obj):
        # Read permissions are allowed only for authenticated users who own the object
        # For MVP, we don't allow public read access
        return obj.user == request.user


class ResumeViewSet(viewsets.ModelViewSet):
    """
    API endpoint for Resume CRUD operations.

    list: GET /api/v1/resumes/ - List all resumes for current user
    create: POST /api/v1/resumes/ - Create a new resume
    retrieve: GET /api/v1/resumes/{id}/ - Get resume detail
    update: PUT /api/v1/resumes/{id}/ - Full update
    partial_update: PATCH /api/v1/resumes/{id}/ - Partial update
    destroy: DELETE /api/v1/resumes/{id}/ - Delete resume
    """

    permission_classes = [permissions.IsAuthenticated, IsOwnerOrReadOnly]

    def get_queryset(self):
        """Return only resumes belonging to the current user."""
        return Resume.objects.filter(user=self.request.user).order_by("-updated_at")

    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == "list":
            return ResumeListSerializer
        elif self.action == "create":
            return ResumeCreateSerializer
        return ResumeDetailSerializer

    def create(self, request, *args, **kwargs):
        """Override create to check quota before creating resume."""
        from django.conf import settings

        profile = request.user.profile
        if not profile.can_create_resume():
            return Response(
                {
                    "error": f"Resume limit reached. Free plan allows {settings.FREE_TIER_LIMITS['resume_count']} resumes. Upgrade to Pro for unlimited resumes."
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        """Set the user to current user when creating."""
        serializer.save(user=self.request.user)

    @action(detail=True, methods=["post"])
    def duplicate(self, request, pk=None):
        """
        Duplicate an existing resume.
        POST /api/v1/resumes/{id}/duplicate/
        QUOTA: Checks resume creation limit for free users.
        """
        # QUOTA: Check resume creation limit
        profile = request.user.profile
        if not profile.can_create_resume():
            return Response(
                {
                    "error": "Resume limit reached. Free plan allows 3 resumes. Upgrade to Pro for unlimited resumes."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        resume = self.get_object()
        new_resume = Resume.objects.create(
            user=request.user,
            title=f"{resume.title} (Copy)",
            content=resume.content.copy(),
        )
        serializer = ResumeDetailSerializer(new_resume)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


def _coerce_rating(value):
    """Return an int 1-5, or None when no rating was given.

    Accepts ints, int()-coercible strings ("4"), and whole-number floats
    (4.0 — common JSON serializer output). Raises ValueError for anything
    else, including bools (an int subclass) and out-of-range values.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError
        value = int(value)
    elif isinstance(value, str):
        value = int(value)
    if not isinstance(value, int) or value not in range(1, 6):
        raise ValueError
    return value


@require_http_methods(["POST"])
def submit_feedback(request):
    """Submit user feedback. Auth optional."""
    try:
        data = json.loads(request.body)
        message = data.get("message", "").strip()
        if not message:
            return JsonResponse({"error": "Message is required"}, status=400)
        try:
            rating = _coerce_rating(data.get("rating"))
        except ValueError:
            return JsonResponse(
                {"error": "Rating must be a whole number between 1 and 5"},
                status=400,
            )
        page = data.get("page", "")
        Feedback.objects.create(
            user=request.user if request.user.is_authenticated else None,
            message=message[:2000],
            rating=rating,
            page=page[:100],
        )
        return JsonResponse({"success": True})
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    except Exception:
        logger.exception("Unexpected error in submit_feedback")
        return JsonResponse({"error": "An unexpected error occurred."}, status=500)
