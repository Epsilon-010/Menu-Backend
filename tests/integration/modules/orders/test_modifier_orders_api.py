"""Slice 15: a table picks options for its dishes; the backend prices them and every view shows them."""

from typing import Any

from fastapi.testclient import TestClient

from app.seed import SeedResult
from tests.integration.modules.catalog.test_catalog_api import ITEMS_URL, Json, create_category, create_item, ok
from tests.integration.modules.catalog.test_modifiers_api import GROUPS_URL, create_group
from tests.integration.modules.orders.test_kitchen_api import DELIVERIES_URL, KITCHEN_URL
from tests.integration.modules.orders.test_ordering_api import (
    LINES_URL,
    add,
    cart,
    staff_of,
    submit,
    tables_overview,
)
from tests.integration.modules.orders.test_paid_bills_api import add_dish
from tests.integration.modules.tables.test_tables_api import (  # noqa: F401  (fixtures)
    ClientFactory,
    admin_of,
    create_table,
    created,
    new_client,
    tablet_of,
    tenant_a,
    tenant_b,
)

EXTRAS = {
    "name": "Extras",
    "min_select": 0,
    "max_select": 2,
    "options": [
        {"name": "Cheese", "price_cents": 500},
        {"name": "Avocado", "price_cents": 900},
        {"name": "Onion", "price_cents": 0},
    ],
}


class Menu:
    """A taco (2500) with Size (Small 0 / Large 1500, pick 1) and Extras (pick up to 2); a plain water."""

    def __init__(self, admin: TestClient) -> None:
        self.admin = admin
        self.size = ok(create_group(admin), 201)
        self.extras = ok(create_group(admin, EXTRAS), 201)
        category = ok(create_category(admin, "Tacos"), 201)["id"]
        self.taco = ok(create_item(admin, category, "Taco", 2500), 201)["id"]
        self.water = ok(create_item(admin, category, "Agua", 1000), 201)["id"]
        ok(admin.patch(f"{ITEMS_URL}/{self.taco}", json={"modifier_group_ids": [self.size["id"], self.extras["id"]]}))

    def option(self, name: str) -> str:
        for group in (self.size, self.extras):
            for option in group["options"]:
                if option["name"] == name:
                    return str(option["id"])
        raise KeyError(name)

    def options(self, *names: str) -> list[str]:
        return [self.option(name) for name in names]

    def edit_group(self, group: Json, **changes: Any) -> Json:
        updated = ok(self.admin.patch(f"{GROUPS_URL}/{group['id']}", json=changes))
        return updated


def setup(new_client: ClientFactory) -> tuple[TestClient, Menu, TestClient]:
    admin = admin_of(new_client)
    menu = Menu(admin)
    tablet = tablet_of(new_client, created(create_table(admin)))
    return admin, menu, tablet


def modifiers(line: Json) -> list[tuple[str, str, int]]:
    return [(m["group"], m["name"], m["price_cents"]) for m in line["modifiers"]]


# --- S4, S7: the cart prices the options ---------------------------------------------------------


def test_a_line_with_options_is_priced_by_the_backend(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    _, menu, tablet = setup(new_client)

    body = ok(add(tablet, menu.taco, 2, modifier_option_ids=menu.options("Avocado", "Large", "Cheese")))

    line = body["lines"][0]
    assert modifiers(line) == [("Size", "Large", 1500), ("Extras", "Cheese", 500), ("Extras", "Avocado", 900)]
    assert [m["option_id"] for m in line["modifiers"]] == menu.options("Large", "Cheese", "Avocado")
    assert (line["unit_price_cents"], line["subtotal_cents"], body["total_cents"]) == (5400, 10800, 10800)
    # A dish without groups works as before.
    plain = ok(add(tablet, menu.water))["lines"][1]
    assert (plain["modifiers"], plain["unit_price_cents"]) == ([], 1000)


def test_a_selection_must_follow_the_group_rules(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    _, menu, tablet = setup(new_client)

    cases = [
        ([], "Choose 1 option for Size"),
        (menu.options("Small", "Large"), "Choose 1 option for Size"),
        (menu.options("Small", "Cheese", "Avocado", "Onion"), "Choose up to 2 options for Extras"),
        (menu.options("Small", "Small"), "Each option can be chosen once"),
        ([menu.option("Small"), str(menu.extras["id"])], "Unknown option"),
    ]
    for selection, detail in cases:
        response = add(tablet, menu.taco, modifier_option_ids=selection)
        assert (response.status_code, response.json()["detail"]) == (422, detail), selection
    other_item = add(tablet, menu.water, modifier_option_ids=menu.options("Small"))
    assert (other_item.status_code, other_item.json()["detail"]) == (422, "Unknown option")
    assert cart(tablet)["lines"] == []


def test_a_sold_out_option_cannot_be_chosen(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    _, menu, tablet = setup(new_client)
    small, large = menu.size["options"]
    menu.edit_group(menu.size, options=[small, {**large, "is_available": False}])

    refused = add(tablet, menu.taco, modifier_option_ids=menu.options("Large"))

    assert refused.status_code == 409
    assert refused.json()["unavailable_item_ids"] == [menu.taco]
    assert ok(add(tablet, menu.taco, modifier_option_ids=menu.options("Small")))["total_cents"] == 2500


def test_anyone_at_the_table_edits_a_lines_options(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin, menu, tablet = setup(new_client)
    other = tablet_of(new_client, created(create_table(admin, "Mesa 9")))
    body = ok(add(tablet, menu.taco, modifier_option_ids=menu.options("Small")))
    line = body["lines"][0]

    edited = ok(tablet.patch(f"{LINES_URL}/{line['id']}", json={"modifier_option_ids": menu.options("Large", "Onion")}))

    assert edited["version"] == body["version"] + 1
    assert modifiers(edited["lines"][0]) == [("Size", "Large", 1500), ("Extras", "Onion", 0)]
    assert edited["lines"][0]["unit_price_cents"] == 4000
    # Quantity edits keep the options; an invalid edit changes nothing.
    assert modifiers(ok(tablet.patch(f"{LINES_URL}/{line['id']}", json={"quantity": 3}))["lines"][0]) == modifiers(
        edited["lines"][0]
    )
    invalid = tablet.patch(f"{LINES_URL}/{line['id']}", json={"modifier_option_ids": []})
    assert (invalid.status_code, invalid.json()["detail"]) == (422, "Choose 1 option for Size")
    assert cart(tablet)["lines"][0]["quantity"] == 3
    # Another table never edits this line.
    assert other.patch(f"{LINES_URL}/{line['id']}", json={"modifier_option_ids": menu.options("Small")}).status_code == 404


def test_repeating_an_add_with_its_id_compares_the_options(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    _, menu, tablet = setup(new_client)
    line_id = "4f6bde0e-35e6-4b48-a2e2-0d7b8c0f8c11"
    first = ok(add(tablet, menu.taco, id=line_id, modifier_option_ids=menu.options("Large", "Cheese")))

    again = ok(add(tablet, menu.taco, id=line_id, modifier_option_ids=menu.options("Cheese", "Large")))
    clash = add(tablet, menu.taco, id=line_id, modifier_option_ids=menu.options("Small"))

    assert again == first
    assert clash.status_code == 409
    # A repeated option is refused even when the rest matches the stored line (verifier advisory 1).
    doubled = add(tablet, menu.taco, id=line_id, modifier_option_ids=menu.options("Large", "Cheese", "Cheese"))
    assert (doubled.status_code, doubled.json()["detail"]) == (422, "Each option can be chosen once")


# --- S5, S8: the menu changes after a line was added ---------------------------------------------


def test_a_line_whose_options_changed_becomes_unavailable_and_blocks_the_send(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    _, menu, tablet = setup(new_client)
    ok(add(tablet, menu.water))
    body = ok(add(tablet, menu.taco, modifier_option_ids=menu.options("Large", "Cheese")))
    cheese = menu.option("Cheese")
    menu.edit_group(menu.extras, options=[o for o in menu.extras["options"] if o["id"] != cheese])

    stale = cart(tablet)
    assert [(line["available"], line["unit_price_cents"]) for line in stale["lines"]] == [(True, 1000), (False, None)]
    # The unavailable line still shows the options that exist, so the table can fix it (verifier advisory 2).
    assert modifiers(stale["lines"][1]) == [("Size", "Large", 1500)]
    assert stale["total_cents"] == 1000

    refused = submit(tablet, stale["version"])
    assert refused.status_code == 409
    assert refused.json()["unavailable_item_ids"] == [menu.taco]

    # Fixing the options lets the table send it.
    line_id = body["lines"][1]["id"]
    fixed = ok(tablet.patch(f"{LINES_URL}/{line_id}", json={"modifier_option_ids": menu.options("Large")}))
    assert ok(submit(tablet, fixed["version"]), 201)["total_cents"] == 1000 + 4000


# --- S9: orders keep a copy; staff views show the options ----------------------------------------


def test_sent_orders_keep_their_options_and_every_view_shows_them(
    new_client: ClientFactory, tenant_a: SeedResult
) -> None:
    admin, menu, tablet = setup(new_client)
    waiter = staff_of(new_client, admin, "juan.mesero", "waiter")
    cook = staff_of(new_client, admin, "test.cocina", "kitchen")
    body = ok(add(tablet, menu.taco, 2, modifier_option_ids=menu.options("Large", "Avocado")))

    order = ok(submit(tablet, body["version"]), 201)

    dish = order["items"][0]
    assert modifiers(dish) == [("Size", "Large", 1500), ("Extras", "Avocado", 900)]
    assert (dish["unit_price_cents"], dish["subtotal_cents"], order["total_cents"]) == (4900, 9800, 9800)

    # Editing the menu later never changes the sent order.
    menu.edit_group(menu.size, options=[{**o, "price_cents": 9999} for o in menu.size["options"]])
    bill_orders = [o for t in tables_overview(waiter) if t["bill"] for o in t["bill"]["orders"]]
    assert bill_orders[0]["items"][0]["modifiers"] == dish["modifiers"]
    assert bill_orders[0]["total_cents"] == 9800

    for client, url in ((cook, KITCHEN_URL), (admin, KITCHEN_URL)):
        staff_dish = ok(client.get(url))[0]["items"][0]  # type: ignore[index]
        assert staff_dish["modifiers"] == [{"group": "Size", "name": "Large"}, {"group": "Extras", "name": "Avocado"}]
    ok(cook.post(f"/api/v1/orders/{order['id']}/items/status", json={"item_ids": [dish["id"]], "status": "ready"}))
    delivery = ok(waiter.get(DELIVERIES_URL))[0]["items"][0]  # type: ignore[index]
    assert delivery["modifiers"] == [{"group": "Size", "name": "Large"}, {"group": "Extras", "name": "Avocado"}]


def test_staff_add_a_dish_with_its_options(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin, menu, tablet = setup(new_client)
    waiter = staff_of(new_client, admin, "juan.mesero", "waiter")
    order = ok(submit(tablet, ok(add(tablet, menu.water))["version"]), 201)

    refused = add_dish(waiter, order, menu.taco)
    updated = ok(add_dish(waiter, order, menu.taco, modifier_option_ids=menu.options("Small", "Cheese")), 201)

    assert (refused.status_code, refused.json()["detail"]) == (422, "Choose 1 option for Size")
    dish = updated["items"][-1]
    assert modifiers(dish) == [("Size", "Small", 0), ("Extras", "Cheese", 500)]
    assert (dish["unit_price_cents"], updated["total_cents"]) == (3000, 4000)
