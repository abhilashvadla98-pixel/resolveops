from enum import Enum

from pydantic import BaseModel, EmailStr


class CustomerTier(str, Enum):
    STANDARD = "standard"
    GOLD = "gold"
    ENTERPRISE = "enterprise"


class CustomerStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class Customer(BaseModel):
    customer_id: str
    name: str
    email: EmailStr
    tier: CustomerTier
    status: CustomerStatus