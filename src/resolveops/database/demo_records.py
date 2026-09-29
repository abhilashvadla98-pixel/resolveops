from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from resolveops.database.base import Base


class DemoScenarioRecord(Base):
    __tablename__ = "demo_scenarios"

    scenario_id: Mapped[str] = mapped_column(String(8), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str] = mapped_column(String(32))
    case_id: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(Text)
