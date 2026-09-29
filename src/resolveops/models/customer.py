from enum import Enum

from pydantic import EmailStr

from resolveops.models.common import DomainModel, Identifier, NonEmptyText


class CustomerTier(str, Enum):
    STANDARD = "standard"
    GOLD = "gold"
    ENTERPRISE = "enterprise"


class CustomerStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class Customer(DomainModel):
    customer_id: Identifier
    name: NonEmptyText
    email: EmailStr
    tier: CustomerTier
    status: CustomerStatus
