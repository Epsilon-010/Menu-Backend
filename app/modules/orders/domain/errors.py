class InvalidOrderData(ValueError):
    pass


class TableNotFound(Exception):
    """No active table with that id in the caller's tenant."""


class BillNotFound(Exception):
    """No bill with that id in the caller's tenant (or it is already closed)."""


class TableNotOpen(Exception):
    """A guest tried to join, or act on, a table whose bill is closed (or was never opened)."""


class QrNotValid(Exception):
    """The QR is not (or no longer) the table's: it was replaced, or the table was deactivated."""


class DinerNotAllowed(Exception):
    """The guest's visit has ended or the tablet was signed out: nothing more can be ordered."""


class CartLineNotFound(Exception):
    pass


class CartChanged(Exception):
    """The cart changed after the sender reviewed it: they must review it again."""


class CartEmpty(Exception):
    pass


class CartFull(Exception):
    pass


class ItemsUnavailable(Exception):
    """Some items in the cart are no longer on the menu."""


class BillHasOrders(Exception):
    """A bill with orders can only be closed by paying it."""


class OrderIdTaken(Exception):
    """A client-chosen id already belongs to another order, cart line or tenant."""


class OrderNotFound(Exception):
    """No order with that id in the caller's tenant."""


class DishesNotInOrder(Exception):
    """A status change named dishes that are not part of the order."""


class TransitionNotAllowed(Exception):
    """The caller's role cannot move dishes to this status (args[0] is the target status)."""


class DishesChanged(Exception):
    """Some dishes are no longer in a state the change can start from: nothing was changed."""
