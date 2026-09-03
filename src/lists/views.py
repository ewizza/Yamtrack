import logging

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Max, OuterRef, Q, Subquery
from django.http import (
    Http404,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotFound,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from app import helpers
from app.models import Item, MediaManager, MediaTypes
from app.providers import services
from lists.forms import CustomListForm
from lists.models import CustomList, CustomListItem
from users.models import (
    LayoutChoices,
    ListDetailSortChoices,
    ListSortChoices,
    MediaStatusChoices,
)

logger = logging.getLogger(__name__)


@require_GET
def lists(request):
    """Return the custom list page."""
    # Get parameters from request
    search_query = request.GET.get("q", "")
    page = request.GET.get("page", 1)
    sort_by = request.user.update_preference("lists_sort", request.GET.get("sort"))

    custom_lists = CustomList.objects.get_user_lists(request.user)

    if search_query:
        custom_lists = custom_lists.filter(
            Q(name__icontains=search_query) | Q(description__icontains=search_query),
        )

    if sort_by == "name":
        custom_lists = custom_lists.order_by("name")
    elif sort_by == "items_count":
        custom_lists = custom_lists.annotate(
            items_count=Count("items", distinct=True),
        ).order_by("-items_count")
    elif sort_by == "newest_first":
        custom_lists = custom_lists.order_by("-id")
    else:  # last_item_added is the default
        # Get the latest update date for each list
        custom_lists = custom_lists.annotate(
            latest_update=Subquery(
                CustomListItem.objects.filter(
                    custom_list=OuterRef("pk"),
                )
                .order_by("-date_added")
                .values("date_added")[:1],
            ),
        ).order_by("-latest_update", "name")

    items_per_page = 20
    paginator = Paginator(custom_lists, items_per_page)
    lists_page = paginator.get_page(page)

    # Create a form for each list
    # needs unique id for django-select2
    for i, custom_list in enumerate(lists_page, start=1):
        custom_list.form = CustomListForm(
            instance=custom_list,
            auto_id=f"id_{i}_%s",
        )

    if request.headers.get("HX-Request"):
        return render(
            request,
            "lists/components/list_grid.html",
            {
                "custom_lists": lists_page,
            },
        )

    create_list_form = CustomListForm()

    return render(
        request,
        "lists/custom_lists.html",
        {
            "custom_lists": lists_page,
            "form": create_list_form,
            "current_sort": sort_by,
            "sort_choices": ListSortChoices.choices,
        },
    )


@require_GET
def list_detail(request, list_id):
    """Return the detail page of a custom list."""
    custom_list = get_object_or_404(
        CustomList.objects.select_related("owner").prefetch_related("collaborators"),
        id=list_id,
    )

    if not custom_list.user_can_view(request.user):
        msg = "List not found"
        raise Http404(msg)

    # Get and process request parameters
    params = {
        "sort_by": request.user.update_preference(
            "list_detail_sort",
            request.GET.get("sort"),
        ),
        "media_type": request.GET.get("type", "all"),
        "status_filter": request.user.update_preference(
            "list_detail_status",
            request.GET.get("status"),
        ),
        "layout": request.user.update_preference(
            "list_detail_layout",
            request.GET.get("layout"),
        ),
        "page": int(request.GET.get("page", 1)),
        "search_query": request.GET.get("q", ""),
    }

    # Build and filter base queryset
    # list_order lets the template show/edit each item's manual position
    # even when other sorts are active.
    items = custom_list.items.annotate(list_order=F("customlistitem__order"))
    if params["search_query"]:
        items = items.filter(title__icontains=params["search_query"])
    if params["media_type"] != "all":
        items = items.filter(media_type=params["media_type"])

    # Get distinct media types for filtering
    media_types = items.values_list("media_type", flat=True).distinct()
    media_manager = MediaManager()
    media_by_item_id = {}

    # Filter by status if specified
    if params["status_filter"] != MediaStatusChoices.ALL:
        item_ids = items.values_list("id", flat=True)
        media_by_item_id = media_manager.fetch_media_for_items(
            media_types,
            item_ids,
            request.user,
            status_filter=params["status_filter"],
        )
        # Filter items to only those with the specified status
        items = items.filter(id__in=media_by_item_id.keys())

    # Apply sorting
    sort_mapping = {
        "date_added": ["-customlistitem__date_added"],
        "title": [
            F("title").asc(nulls_last=True),
            F("season_number").asc(nulls_first=True),
            F("episode_number").asc(nulls_first=True),
        ],
        "media_type": ["media_type"],
        "custom": ["customlistitem__order"],
    }
    items = items.order_by(
        *sort_mapping.get(params["sort_by"], ["-customlistitem__date_added"]),
    )

    # Paginate
    paginator = Paginator(items, 16)
    items_page = paginator.get_page(params["page"])

    # If no status filter was applied, fetch media objects for paginated items only
    if params["status_filter"] == MediaStatusChoices.ALL:
        media_types_in_page = {item.media_type for item in items_page}
        page_item_ids = [item.id for item in items_page]
        media_by_item_id = media_manager.fetch_media_for_items(
            media_types_in_page,
            page_item_ids,
            request.user,
        )

    # Annotate items with media objects
    for item in items_page:
        item.media = media_by_item_id.get(item.id)

    # Base context for both full and partial responses
    context = {
        "custom_list": custom_list,
        "items": items_page,
        "has_next": items_page.has_next(),
        "next_page_number": items_page.next_page_number()
        if items_page.has_next()
        else None,
        "current_sort": params["sort_by"],
        "current_status": params["status_filter"] or MediaStatusChoices.ALL,
        "current_layout": params["layout"],
        "sort_choices": ListDetailSortChoices.choices,
        "status_choices": MediaStatusChoices.choices,
        "layout_choices": LayoutChoices.choices,
        # Drag-to-reorder and manual position entry only make sense on the
        # "custom" sort, and only for users who can actually edit the list.
        "can_reorder": params["sort_by"] == "custom"
        and custom_list.user_can_edit(request.user),
        "list_total_items": custom_list.items.count(),
    }

    # Additional context for full page render. Soft-navigation body swaps (e.g.
    # after saving from an edit modal) also need the full page, not the partial.
    if not request.headers.get("HX-Request") or request.headers.get(
        "X-Soft-Navigation"
    ):
        context.update(
            {
                "form": CustomListForm(instance=custom_list),
                "media_types": MediaTypes.values,
                "items_count": paginator.count,
                "collaborators_count": custom_list.collaborators.count() + 1,
            },
        )
        return render(request, "lists/list_detail.html", context)

    # HTMX partial response
    return render(request, "lists/components/list_items.html", context)


@require_POST
def create(request):
    """Create a new custom list."""
    form = CustomListForm(request.POST)
    if form.is_valid():
        custom_list = form.save(commit=False)
        custom_list.owner = request.user
        custom_list.save()
        form.save_m2m()
        logger.info("%s list created successfully.", custom_list)
    else:
        logger.error(form.errors.as_json())
        helpers.form_error_messages(form, request)
    return helpers.redirect_back(request)


@require_POST
def edit(request):
    """Edit an existing custom list."""
    list_id = request.POST.get("list_id")
    custom_list = get_object_or_404(CustomList, id=list_id)
    if custom_list.user_can_edit(request.user):
        form = CustomListForm(request.POST, instance=custom_list)
        if form.is_valid():
            form.save()
            logger.info("%s list edited successfully.", custom_list)
    else:
        messages.error(request, "You do not have permission to edit this list.")
    return helpers.redirect_back(request)


@require_POST
def delete(request):
    """Delete a custom list."""
    list_id = request.POST.get("list_id")
    custom_list = get_object_or_404(CustomList, id=list_id)
    if custom_list.user_can_delete(request.user):
        custom_list.delete()
        logger.info("%s list deleted successfully.", custom_list)
        return redirect("lists")

    messages.error(request, "You do not have permission to delete this list.")
    return helpers.redirect_back(request)


@require_GET
def lists_modal(
    request,
    source,
    media_type,
    media_id,
    season_number=None,
    episode_number=None,
):
    """Return the modal showing all custom lists and allowing to add to them."""
    try:
        item = Item.objects.get(
            media_id=media_id,
            source=source,
            media_type=media_type,
            season_number=season_number,
            episode_number=episode_number,
        )
    except Item.DoesNotExist:
        metadata = services.get_media_metadata(
            media_type,
            media_id,
            source,
            [season_number],
            episode_number,
        )
        item = Item.objects.create(
            media_id=media_id,
            source=source,
            media_type=media_type,
            season_number=season_number,
            episode_number=episode_number,
            title=metadata["title"],
            image=metadata["image"],
        )

    custom_lists = CustomList.objects.get_user_lists_with_item(request.user, item)

    return render(
        request,
        "lists/components/fill_lists.html",
        {"item": item, "custom_lists": custom_lists},
    )


@require_POST
def list_item_toggle(request):
    """Add or remove an item from a custom list."""
    item_id = request.POST["item_id"]
    custom_list_id = request.POST["custom_list_id"]

    item = get_object_or_404(Item, id=item_id)
    custom_list = get_object_or_404(
        CustomList.objects.filter(
            Q(owner=request.user) | Q(collaborators=request.user),
            id=custom_list_id,
        ).distinct(),  # To prevent duplicates, when user is owner and collaborator
    )

    if custom_list.items.filter(id=item.id).exists():
        custom_list.items.remove(item)
        logger.info("%s removed from %s.", item, custom_list)
        has_item = False
    else:
        with transaction.atomic():
            # Lock the list's existing rows so two concurrent adds can't
            # compute the same "next" order and collide.
            max_order = (
                CustomListItem.objects.select_for_update()
                .filter(custom_list=custom_list)
                .aggregate(Max("order"))["order__max"]
            )
            next_order = 0 if max_order is None else max_order + 1
            CustomListItem.objects.create(
                custom_list=custom_list,
                item=item,
                order=next_order,
            )
        logger.info("%s added to %s.", item, custom_list)
        has_item = True

    return render(
        request,
        "lists/components/list_item_button.html",
        {"custom_list": custom_list, "item": item, "has_item": has_item},
    )


@require_POST
def list_item_reorder(request):
    """Persist a new manual order for the items of a custom list.

    Expects `list_id` and a repeated `item_id` field giving the items'
    Item ids in their new order. Only the items included in the request are
    touched; any item not passed (e.g. filtered out client-side) keeps its
    existing position relative to the others.
    """
    list_id = request.POST.get("list_id")
    item_ids = request.POST.getlist("item_id")

    custom_list = get_object_or_404(CustomList, id=list_id)
    if not custom_list.user_can_edit(request.user):
        return HttpResponseForbidden()

    try:
        ordered_ids = [int(item_id) for item_id in item_ids]
    except (TypeError, ValueError):
        return HttpResponseForbidden()

    with transaction.atomic():
        # Lock the affected rows first so two concurrent reorders on the
        # same list can't interleave and leave duplicate/gapped ranks.
        list_items = (
            CustomListItem.objects.select_for_update()
            .filter(custom_list=custom_list, item_id__in=ordered_ids)
            .select_related(None)
        )
        item_id_to_list_item = {li.item_id: li for li in list_items}

        to_update = []
        for rank, item_id in enumerate(ordered_ids):
            list_item = item_id_to_list_item.get(item_id)
            if list_item is not None and list_item.order != rank:
                list_item.order = rank
                to_update.append(list_item)

        if to_update:
            CustomListItem.objects.bulk_update(to_update, ["order"])

    logger.info("%s reordered.", custom_list)
    return HttpResponse(status=204)


@require_POST
def list_item_move(request):
    """Move a single item to an absolute 1-based position in its list.

    Unlike `list_item_reorder` (which re-ranks a batch of items the browser
    already has loaded, for drag-and-drop), this walks the *entire* list
    server-side. That makes it the only way to reorder items that are more
    than a page/scroll-load apart, e.g. moving item #200 to position #4 in a
    long list without dragging it through everything in between.
    """
    list_id = request.POST.get("list_id")
    item_id = request.POST.get("item_id")
    position = request.POST.get("position")

    custom_list = get_object_or_404(CustomList, id=list_id)
    if not custom_list.user_can_edit(request.user):
        return HttpResponseForbidden()

    try:
        item_id = int(item_id)
        position = int(position)
    except (TypeError, ValueError):
        return HttpResponseBadRequest("item_id and position must be integers.")

    if position < 1:
        return HttpResponseBadRequest("position must be at least 1.")

    with transaction.atomic():
        # Lock and load every item in the list, in its current order, so the
        # whole-list reinsertion below can't race with another move/reorder.
        list_items = list(
            CustomListItem.objects.select_for_update()
            .filter(custom_list=custom_list)
            .order_by("order", "date_added"),
        )

        moving = next((li for li in list_items if li.item_id == item_id), None)
        if moving is None:
            return HttpResponseNotFound()

        list_items.remove(moving)
        # 1-based position -> 0-based index, clamped to the end of the list.
        target_index = min(position - 1, len(list_items))
        list_items.insert(target_index, moving)

        to_update = []
        for rank, list_item in enumerate(list_items):
            if list_item.order != rank:
                list_item.order = rank
                to_update.append(list_item)

        if to_update:
            CustomListItem.objects.bulk_update(to_update, ["order"])

    logger.info("%s item moved to position %s.", custom_list, position)
    return HttpResponse(status=204)
