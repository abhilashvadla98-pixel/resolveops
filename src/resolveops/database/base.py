from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Keep metadata complete even when a focused test imports Base before the seed module.
from resolveops.database import agent_records as _agent_records  # noqa: F401
from resolveops.database import demo_records as _demo_records  # noqa: F401
from resolveops.database import feedback_records as _feedback_records  # noqa: F401
