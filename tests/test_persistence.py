from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from resolveops.database.base import Base
from resolveops.database.records import CustomerRecord, PaymentRecord, ReturnRecord
from resolveops.database.seed import seed_customer_operations
from resolveops.database.store import CustomerOperationsStore
from resolveops.domain.billing import find_possible_duplicate_charges


def sqlite_engine() -> Engine:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return engine


def test_seed_data_round_trips_complete_customer_case() -> None:
    engine = sqlite_engine()
    with Session(engine) as session:
        assert seed_customer_operations(session) is True
        session.commit()
        assert seed_customer_operations(session) is False

        store = CustomerOperationsStore(session)
        customer = store.get_customer("CUST-1001")
        order = store.get_order("ORD-48391")
        payments = store.list_payments("ORD-48391")
        customer_return = store.get_return("RET-3001")
        customer_case = store.get_case("CASE-1001")
        refund = store.get_refund("REF-2001")

        assert customer is not None and customer.name == "Maya Patel"
        assert order is not None and len(order.items) == 2
        assert len(payments) == 2
        assert len(find_possible_duplicate_charges(payments)) == 1
        assert customer_return is not None
        assert customer_return.refund_ids == ["REF-2001"]
        assert customer_case is not None and len(customer_case.issues) == 2
        assert customer_case.issues[0].payment_ids == ["PAY-1001", "PAY-1002"]
        assert customer_case.issues[1].return_id == "RET-3001"
        assert refund is not None and refund.issue_id == "ISSUE-1002"

    engine.dispose()


def test_database_rejects_negative_payment_amount() -> None:
    engine = sqlite_engine()
    with Session(engine) as session:
        seed_customer_operations(session)
        session.commit()
        session.add(
            PaymentRecord(
                payment_id="PAY-BAD",
                order_id="ORD-48391",
                amount="-1.00",
                currency="USD",
                status="captured",
                created_at=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
                captured_at=datetime(2026, 9, 1, 10, 1, tzinfo=UTC),
            )
        )

        with pytest.raises(IntegrityError):
            session.commit()

    engine.dispose()


def test_database_rejects_return_for_wrong_customer() -> None:
    engine = sqlite_engine()
    with Session(engine) as session:
        seed_customer_operations(session)
        session.add(
            CustomerRecord(
                customer_id="CUST-OTHER",
                name="Other Customer",
                email="other@example.com",
                tier="standard",
                status="active",
            )
        )
        session.commit()
        session.add(
            ReturnRecord(
                return_id="RET-WRONG-CUSTOMER",
                order_id="ORD-48391",
                customer_id="CUST-OTHER",
                status="requested",
                created_at=datetime(2026, 9, 20, 10, 0, tzinfo=UTC),
            )
        )

        with pytest.raises(IntegrityError):
            session.commit()

    engine.dispose()
