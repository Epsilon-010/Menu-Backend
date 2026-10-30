import uuid

from fastapi.testclient import TestClient
from httpx import Response

from app.seed import SeedResult
from tests.integration.modules.auth.test_auth_api import login
from tests.integration.modules.catalog.test_catalog_api import (
    ITEMS_URL,
    CATALOG_URL,
    ClientFactory,
    Json,
    admin_of,
    catalog,
    create_category,
    create_item,
    images,  # noqa: F401  (fixture)
    new_client,  # noqa: F401  (fixture)
    ok,
    tenant_a,  # noqa: F401  (fixture)
    tenant_b,  # noqa: F401  (fixture)
)
from tests.integration.modules.catalog.test_menu_api import MENU_URL, menu
from tests.integration.modules.staff.test_staff_api import STAFF_PASSWORD, create_member, member_id
from tests.integration.modules.tables.test_tables_api import create_table, created, tablet_of

GROUPS_URL = f"{CATALOG_URL}/modifier-groups"

SIZE = {
    "name": "Size",
    "min_select": 1,
    "max_select": 1,
    "options": [{"name": "Small", "price_cents": 0}, {"name": "Large", "price_cents": 1500}],
}


def create_group(admin: TestClient, body: Json | None = None, **changes: object) -> Response:
    return admin.post(GROUPS_URL, json={**(body or SIZE), **changes})


def groups(admin: TestClient) -> list[Json]:
    body: list[Json] = ok(admin.get(GROUPS_URL))  # type: ignore[assignment]
    return body


def item_with(admin: TestClient, group_ids: list[str], name: str = "Pastor") -> Json:
    category = ok(create_category(admin, f"Tacos {uuid.uuid4().hex[:6]}"), 201)
    item = ok(create_item(admin, category["id"], name), 201)
    return ok(admin.patch(f"{ITEMS_URL}/{item['id']}", json={"modifier_group_ids": group_ids}))


# --- S1, S2: the library ------------------------------------------------------------------------


def test_admin_creates_lists_edits_and_deletes_groups(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)

    size = ok(create_group(admin), 201)
    ok(create_group(admin, name="extras", min_select=0, max_select=2), 201)

    assert [g["name"] for g in groups(admin)] == ["extras", "Size"]
    assert [(o["name"], o["price_cents"], o["is_available"]) for o in size["options"]] == [
        ("Small", 0, True),
        ("Large", 1500, True),
    ]

    large = size["options"][1]
    edited = ok(
        admin.patch(
            f"{GROUPS_URL}/{size['id']}",
            json={"options": [{**large, "is_available": False}, {"name": "Medium", "price_cents": 800}]},
        )
    )
    assert [o["name"] for o in edited["options"]] == ["Large", "Medium"]
    assert edited["options"][0]["id"] == large["id"] and edited["options"][0]["is_available"] is False
    assert [g for g in groups(admin) if g["id"] == size["id"]] == [edited]

    assert admin.delete(f"{GROUPS_URL}/{size['id']}").status_code == 204
    assert admin.delete(f"{GROUPS_URL}/{size['id']}").status_code == 404
    assert [g["name"] for g in groups(admin)] == ["extras"]


def test_group_rules_are_validated_without_echoing_values(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    size = ok(create_group(admin), 201)

    cases = [
        ({"min_select": 2, "max_select": 1}, "Invalid selection limits"),
        ({"max_select": 3}, "Invalid selection limits"),
        ({"options": []}, "A group must have 1 to 30 options"),
        ({"options": [{"name": "Cheese", "price_cents": 0}, {"name": "CHEESE", "price_cents": 0}]}, "Option names must be unique in a group"),
        ({"name": " "}, "Group name must have 1 to 80 characters"),
    ]
    for changes, detail in cases:
        response = create_group(admin, **changes)
        assert (response.status_code, response.json()["detail"]) == (422, detail), changes

    negative = create_group(admin, options=[{"name": "Large", "price_cents": -1}])
    assert negative.status_code == 422 and "-1" not in negative.text
    unknown = admin.patch(f"{GROUPS_URL}/{size['id']}", json={"options": [{"id": str(uuid.uuid4()), "name": "X", "price_cents": 0}]})
    assert (unknown.status_code, unknown.json()["detail"]) == (422, "Unknown option")
    assert create_group(admin, color="red").status_code == 422


def test_repeating_a_create_is_idempotent_and_a_reused_id_is_409(
    new_client: ClientFactory, tenant_a: SeedResult, tenant_b: SeedResult
) -> None:
    admin = admin_of(new_client)
    other = admin_of(new_client, "boss@example.com")
    group_id = str(uuid.uuid4())

    first = ok(create_group(admin, id=group_id), 201)
    assert ok(create_group(admin, id=group_id), 201) == first
    assert len(groups(admin)) == 1

    for client, body in ((admin, {**SIZE, "name": "Salsas"}), (other, SIZE)):
        response = create_group(client, body, id=group_id)
        assert (response.status_code, response.json()["detail"]) == (409, "That id is already used by something else")
    assert groups(other) == []


def test_items_use_groups_in_order_and_unknown_ones_are_rejected(
    new_client: ClientFactory, tenant_a: SeedResult, tenant_b: SeedResult
) -> None:
    admin = admin_of(new_client)
    size = ok(create_group(admin), 201)
    extras = ok(create_group(admin, name="Extras", min_select=0), 201)
    foreign = ok(create_group(admin_of(new_client, "boss@example.com")), 201)

    item = item_with(admin, [extras["id"], size["id"], extras["id"]])
    assert item["modifier_group_ids"] == [extras["id"], size["id"]]

    category = ok(create_category(admin, "Bebidas"), 201)
    created_item = ok(
        admin.post(
            ITEMS_URL,
            json={"category_id": category["id"], "name": "Agua", "price_cents": 1000, "modifier_group_ids": [size["id"]]},
        ),
        201,
    )
    assert created_item["modifier_group_ids"] == [size["id"]]

    for group_id in (foreign["id"], str(uuid.uuid4())):
        response = admin.patch(f"{ITEMS_URL}/{item['id']}", json={"modifier_group_ids": [group_id]})
        assert (response.status_code, response.json()["detail"]) == (422, "Unknown modifier group")
    # Other edits keep the groups; deleting a group detaches it.
    assert ok(admin.patch(f"{ITEMS_URL}/{item['id']}", json={"price_cents": 3000}))["modifier_group_ids"] == [
        extras["id"],
        size["id"],
    ]
    assert admin.delete(f"{GROUPS_URL}/{extras['id']}").status_code == 204
    listed = [i for c in catalog(admin) for i in c["items"] if i["id"] == item["id"]]
    assert listed[0]["modifier_group_ids"] == [size["id"]]


def test_only_the_admin_of_the_tenant_manages_groups(
    new_client: ClientFactory, tenant_a: SeedResult, tenant_b: SeedResult
) -> None:
    admin = admin_of(new_client)
    size = ok(create_group(admin), 201)
    tablet = tablet_of(new_client, created(create_table(admin)))
    staff = []
    for username, role in (("juan.mesero", "waiter"), ("test.cocina", "kitchen")):
        member_id(create_member(admin, username, role))
        client = new_client()
        assert login(client, username=username, password=STAFF_PASSWORD).status_code == 200
        staff.append(client)

    def every_call(client: TestClient) -> list[int]:
        return [
            client.get(GROUPS_URL).status_code,
            create_group(client).status_code,
            client.patch(f"{GROUPS_URL}/{size['id']}", json={"name": "Hacked"}).status_code,
            client.delete(f"{GROUPS_URL}/{size['id']}").status_code,
        ]

    for client in (tablet, *staff):
        assert every_call(client) == [403] * 4
    assert every_call(new_client()) == [401] * 4

    other = admin_of(new_client, "boss@example.com")
    assert groups(other) == []
    assert other.patch(f"{GROUPS_URL}/{size['id']}", json={"name": "Hacked"}).status_code == 404
    assert other.delete(f"{GROUPS_URL}/{size['id']}").status_code == 404
    assert groups(admin) == [size]


# --- S5, S6: what tables see -----------------------------------------------------------------------


def test_the_menu_shows_each_item_with_its_groups(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    size = ok(create_group(admin), 201)
    large = size["options"][1]
    ok(admin.patch(f"{GROUPS_URL}/{size['id']}", json={"options": [size["options"][0], {**large, "is_available": False}]}))
    item = item_with(admin, [size["id"]])
    plain = item_with(admin, [], name="Suadero")
    tablet = tablet_of(new_client, created(create_table(admin)))

    items = {i["id"]: i for c in menu(tablet) for i in c["items"]}

    assert items[plain["id"]]["modifier_groups"] == []
    assert items[item["id"]]["modifier_groups"] == [
        {
            "id": size["id"],
            "name": "Size",
            "min_select": 1,
            "max_select": 1,
            "options": [
                {"id": size["options"][0]["id"], "name": "Small", "price_cents": 0, "available": True},
                {"id": large["id"], "name": "Large", "price_cents": 1500, "available": False},
            ],
        }
    ]


def test_an_item_whose_required_group_is_sold_out_leaves_the_menu(new_client: ClientFactory, tenant_a: SeedResult) -> None:
    admin = admin_of(new_client)
    size = ok(create_group(admin), 201)
    item = item_with(admin, [size["id"]])
    tablet = tablet_of(new_client, created(create_table(admin)))
    assert item["id"] in {i["id"] for c in menu(tablet) for i in c["items"]}

    sold_out = [{**option, "is_available": False} for option in size["options"]]
    ok(admin.patch(f"{GROUPS_URL}/{size['id']}", json={"options": sold_out}))

    # The group edit invalidated the cached menu.
    assert item["id"] not in {i["id"] for c in menu(tablet) for i in c["items"]}
    assert tablet.get(MENU_URL).status_code == 200
