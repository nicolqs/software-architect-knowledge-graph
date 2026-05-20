"""Pydantic models for the Architect agent's structured outputs.

Each node returns one of these. The final `ArchitectureProposal` aggregates
everything for the UI to render and for the propose_node/propose_edge
writer to stage as graph deltas.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ServiceLayer = Literal["edge", "api", "domain", "data", "infra"]
NfrArea = Literal["scaling", "observability", "security", "reliability", "cost"]


class ProposedService(BaseModel):
    name: str = Field(..., description="Service name, PascalCase.")
    layer: ServiceLayer
    responsibilities: list[str] = Field(..., min_length=1, max_length=8)
    depends_on: list[str] = Field(
        default_factory=list,
        description="Names of other services in this proposal that this one depends on.",
    )


class ProposedColumn(BaseModel):
    name: str
    type: str = Field(..., description="SQL type, e.g. 'TEXT', 'BIGINT', 'UUID', 'TIMESTAMPTZ'.")
    nullable: bool = True
    primary_key: bool = False


class ProposedTable(BaseModel):
    name: str = Field(..., description="Table name, snake_case.")
    owned_by_service: str = Field(..., description="Name of the ProposedService that owns this.")
    columns: list[ProposedColumn] = Field(..., min_length=1)
    indexes: list[str] = Field(default_factory=list, description="Each entry like 'idx_users_email ON (email)'.")
    foreign_keys: list[str] = Field(
        default_factory=list,
        description="Each entry like 'fk_orders_user_id → users(id)'.",
    )


class ProposedEndpoint(BaseModel):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str = Field(..., description="Path pattern, e.g. '/v1/users/{id}'.")
    summary: str = Field(..., max_length=140)
    owned_by_service: str
    request_shape: str = Field("", description="One-line schema sketch; empty for methods without a body.")
    response_shape: str = Field("", description="One-line schema sketch.")


class NfrConcern(BaseModel):
    area: NfrArea
    concern: str
    mitigation: str


class ProposedGraphDelta(BaseModel):
    """The list of graph mutations to stage in decision_log."""

    nodes: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Each dict: {label, qname, props}. Label ∈ {Service, API, DBTable, InfraComponent, Feature}.",
    )
    edges: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Each dict: {from_qname, to_qname, rel_type, props}. rel_type ∈ {DEPENDS_ON, OWNS, WRITES_TO, READS_FROM}.",
    )


class ArchitectureProposal(BaseModel):
    """End-to-end output the API route returns to the caller."""

    services: list[ProposedService]
    tables: list[ProposedTable]
    endpoints: list[ProposedEndpoint]
    nfrs: list[NfrConcern]
    markdown: str = Field(..., description="The architecture document, ready to paste into a PR or RFC.")
    graph_delta: ProposedGraphDelta
