# https://docs.djangoproject.com/en/stable/ref/templates/api/#writing-your-own-context-processors

from lists.models import CustomList


def pinned_lists(request):
    """Return the custom lists the current user has pinned to their sidebar.

    Renders on every page (the sidebar isn't scoped to list views), so this
    runs one small, indexed query per authenticated request.
    """
    if not request.user.is_authenticated:
        return {"pinned_lists": []}

    return {
        "pinned_lists": list(
            CustomList.objects.filter(
                pins__user=request.user,
            ).order_by("pins__pinned_at"),
        ),
    }
