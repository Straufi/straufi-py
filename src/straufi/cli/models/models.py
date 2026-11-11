from enum import StrEnum
from typing import NotRequired, TypedDict

Budget = dict[str, dict[str, float]]


class StrategyMode(StrEnum):
    PAPER = "paper"
    LIVE = "live"


class BuildStatus(StrEnum):
    AWAITING_UPLOAD = "awaiting-upload"
    QUEUED = "queued"
    BUILDING = "building"
    AVAILABLE = "available"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    ARCHIVED = "archived"


class InstrumentInfo(TypedDict):
    base: str
    quote: str
    broker: str


class Strategy(TypedDict):
    id: str
    displayName: str
    mode: StrategyMode
    isActive: bool
    baseBudget: Budget
    instruments: list[InstrumentInfo]
    recurrenceDates: list[str]
    activeBuildId: NotRequired[str]
    deployedAt: NotRequired[str]


class Build(TypedDict):
    id: str
    strategyId: str
    status: BuildStatus
    createdAt: str
    failureReason: NotRequired[str]
    failureMessage: NotRequired[str]
    uploadChecksum: NotRequired[str]
    pythonVersion: NotRequired[str]


class CreatedBuild(TypedDict):
    build: Build
    uploadUrl: str
    uploadHeaders: dict[str, str]


class Execution(TypedDict):
    id: str
    buildId: str
    executionTime: str
    status: str
    failureReason: NotRequired[str]
