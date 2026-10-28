import itertools

import pytest

from app.modules.orders.domain.errors import InvalidOrderData, TransitionNotAllowed
from app.modules.orders.domain.model import (
    OrderItemStatus,
    OrderStatus,
    can_transition,
    derive_order_status,
    sources_for,
    validate_change_reason,
)
from app.shared.domain.principal import Role

QUEUED, PREPARING, READY, DELIVERED, CANCELLED = (
    OrderItemStatus.QUEUED,
    OrderItemStatus.PREPARING,
    OrderItemStatus.READY,
    OrderItemStatus.DELIVERED,
    OrderItemStatus.CANCELLED,
)
ALLOWED = {(QUEUED, PREPARING), (QUEUED, READY), (PREPARING, READY), (READY, DELIVERED), (QUEUED, CANCELLED)}


@pytest.mark.parametrize("source, target", list(itertools.product(OrderItemStatus, OrderItemStatus)))
def test_only_the_state_machine_transitions_are_allowed(source: OrderItemStatus, target: OrderItemStatus) -> None:
    assert can_transition(source, target) is ((source, target) in ALLOWED)


def test_a_queued_dish_cannot_jump_to_delivered() -> None:
    assert not can_transition(QUEUED, DELIVERED)


ROLE_TARGETS = {
    Role.ADMIN: {PREPARING, READY, DELIVERED, CANCELLED},
    Role.KITCHEN: {PREPARING, READY, CANCELLED},
    Role.WAITER: {DELIVERED, CANCELLED},
    Role.TABLE: set(),
    Role.GUEST: set(),
}


@pytest.mark.parametrize("role, target", list(itertools.product(Role, OrderItemStatus)))
def test_each_role_marks_only_what_the_permission_matrix_allows(role: Role, target: OrderItemStatus) -> None:
    if target in ROLE_TARGETS[role]:
        assert sources_for(target, role) == {source for source, to in ALLOWED if to is target}
    else:
        with pytest.raises(TransitionNotAllowed) as error:
            sources_for(target, role)
        assert error.value.args[0] is target


def test_cancelling_needs_a_reason_and_keeps_it_trimmed() -> None:
    assert validate_change_reason(CANCELLED, "  out of avocado ") == "out of avocado"
    for missing in (None, "", "   "):
        with pytest.raises(InvalidOrderData, match="A reason is required to cancel dishes"):
            validate_change_reason(CANCELLED, missing)
    with pytest.raises(InvalidOrderData, match="The reason must have at most 200 characters"):
        validate_change_reason(CANCELLED, "x" * 201)
    assert validate_change_reason(CANCELLED, "x" * 200) == "x" * 200


@pytest.mark.parametrize("target", [PREPARING, READY, DELIVERED])
def test_only_cancelling_takes_a_reason(target: OrderItemStatus) -> None:
    assert validate_change_reason(target, None) is None
    with pytest.raises(InvalidOrderData, match="Only cancelled dishes take a reason"):
        validate_change_reason(target, "because")


@pytest.mark.parametrize(
    "statuses, expected",
    [
        ([QUEUED, QUEUED], OrderStatus.QUEUED),
        ([QUEUED, PREPARING], OrderStatus.IN_PROGRESS),
        ([QUEUED, READY], OrderStatus.IN_PROGRESS),
        ([PREPARING, READY], OrderStatus.IN_PROGRESS),
        ([READY, DELIVERED], OrderStatus.PARTIALLY_DELIVERED),
        ([QUEUED, DELIVERED], OrderStatus.PARTIALLY_DELIVERED),
        ([DELIVERED, DELIVERED], OrderStatus.COMPLETED),
        ([DELIVERED, CANCELLED], OrderStatus.COMPLETED),
        ([QUEUED, CANCELLED], OrderStatus.QUEUED),
        ([PREPARING, CANCELLED], OrderStatus.IN_PROGRESS),
        ([READY, DELIVERED, CANCELLED], OrderStatus.PARTIALLY_DELIVERED),
        ([CANCELLED, CANCELLED], OrderStatus.CANCELLED),
        ([], OrderStatus.CANCELLED),
    ],
)
def test_the_order_status_is_derived_from_its_dishes(
    statuses: list[OrderItemStatus], expected: OrderStatus
) -> None:
    assert derive_order_status(statuses) is expected
