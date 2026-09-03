// Drag-to-reorder for custom list items (sort = "custom").
//
// #items-grid is the stable wrapper (holds the reorder/move URLs, list id,
// CSRF token) that htmx swaps the *contents* of when sort/filter/search or
// layout changes. #items-sortable-root is the actual direct parent of the
// sortable rows/cards inside it — a <div class="media-grid"> in grid layout,
// a <tbody> in table layout — and gets recreated on every swap, so we always
// look it up fresh rather than caching it.
//
// Sortable.js delegates drag handling from that root rather than binding
// per-child listeners, so items appended later by infinite-scroll pagination
// are sortable automatically without any extra wiring.
(function () {
  let sortable = null;

  function initSortable() {
    const config = document.getElementById("items-grid");
    const root = document.getElementById("items-sortable-root");

    if (sortable) {
      sortable.destroy();
      sortable = null;
    }

    if (!config || !root) {
      return;
    }

    const hasHandle = root.querySelector(".list-drag-handle") !== null;
    if (!hasHandle) {
      return;
    }

    sortable = new Sortable(root, {
      handle: ".list-drag-handle",
      animation: 150,
      onEnd: () => persistOrder(config, root),
    });
  }

  function persistOrder(config, root) {
    const reorderUrl = config.dataset.reorderUrl;
    const listId = config.dataset.listId;
    const csrfToken = config.dataset.csrf;
    if (!reorderUrl || !listId) {
      return;
    }

    const items = Array.from(root.querySelectorAll("[data-item-id]"));
    const itemIds = items.map((el) => el.dataset.itemId);

    const body = new URLSearchParams();
    body.append("list_id", listId);
    itemIds.forEach((id) => body.append("item_id", id));

    fetch(reorderUrl, {
      method: "POST",
      headers: {
        "X-CSRFToken": csrfToken,
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: body.toString(),
    })
      .then((response) => {
        if (!response.ok) {
          return;
        }
        // The drag only reorders the DOM; each item's position-number input
        // still shows its rank from before the drag. Sync them to the new
        // order so they don't go stale until the next full page load.
        items.forEach((item, index) => {
          const input = item.querySelector(".list-position-input");
          if (input) {
            input.value = String(index + 1);
          }
        });
      })
      .catch((error) => {
        console.error("Failed to save list order", error);
      });
  }

  // Manual "move to position" input, for lists too long to drag across
  // (pagination/infinite scroll). This walks the whole list server-side
  // (see list_item_move), so unlike the drag handler it doesn't need every
  // item loaded in the browser at once — just reload after a successful
  // move to see the list in its new order.
  function persistMove(input) {
    const config = document.getElementById("items-grid");
    if (!config) {
      return;
    }

    const moveUrl = config.dataset.moveUrl;
    const listId = config.dataset.listId;
    const csrfToken = config.dataset.csrf;
    const itemId = input.dataset.moveItemId;
    const position = parseInt(input.value, 10);
    if (!moveUrl || !listId || !itemId || Number.isNaN(position)) {
      return;
    }

    const body = new URLSearchParams();
    body.append("list_id", listId);
    body.append("item_id", itemId);
    body.append("position", String(position));

    input.disabled = true;
    fetch(moveUrl, {
      method: "POST",
      headers: {
        "X-CSRFToken": csrfToken,
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: body.toString(),
    })
      .then((response) => {
        if (response.ok) {
          window.location.reload();
        } else {
          input.disabled = false;
        }
      })
      .catch((error) => {
        console.error("Failed to move list item", error);
        input.disabled = false;
      });
  }

  // Up/down buttons for the position stepper (position_stepper.html). These
  // replace the number input's native spin arrows, which only ever
  // increment on "up" — here "up" means move the item earlier, so it must
  // decrement the position number, and "down" increments it.
  function stepPosition(button, delta) {
    const input = button
      .closest(".list-position-stepper")
      ?.querySelector(".list-position-input");
    if (!input) {
      return;
    }

    const min = parseInt(input.min, 10) || 1;
    const max = parseInt(input.max, 10) || Infinity;
    const current = parseInt(input.value, 10) || min;
    input.value = String(Math.min(max, Math.max(min, current + delta)));
    persistMove(input);
  }

  document.addEventListener("DOMContentLoaded", initSortable);
  document.addEventListener("htmx:afterSwap", (event) => {
    if (event.target && event.target.id === "items-grid") {
      initSortable();
    }
  });

  // Delegated so it keeps working after htmx swaps #items-grid's contents.
  document.addEventListener("change", (event) => {
    if (event.target.matches && event.target.matches(".list-position-input")) {
      persistMove(event.target);
    }
  });
  document.addEventListener("keydown", (event) => {
    if (
      event.key === "Enter" &&
      event.target.matches &&
      event.target.matches(".list-position-input")
    ) {
      event.preventDefault();
      event.target.blur();
    }
  });
  document.addEventListener("click", (event) => {
    const upButton = event.target.closest && event.target.closest(".list-position-up");
    if (upButton) {
      stepPosition(upButton, -1);
      return;
    }
    const downButton = event.target.closest && event.target.closest(".list-position-down");
    if (downButton) {
      stepPosition(downButton, 1);
    }
  });
})();
