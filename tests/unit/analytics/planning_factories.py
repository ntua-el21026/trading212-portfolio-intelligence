"""Synthetic inputs shared by exact-oracle and property tests."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Context, Decimal, localcontext
from typing import Any
from uuid import UUID

from trading212_domain import CurrencyCode, Money, QualityState
from trading212_domain.planning import (
    PlanningInput,
    PlanningMode,
    PlanningNodeIdentity,
    PlanningOptions,
    PlanningSource,
    ValuationCash,
    ValuationInput,
    ValuationPosition,
)
from trading212_domain.targets import (
    TargetCatalog,
    TargetConstraint,
    TargetContent,
    TargetHoldingMapping,
    TargetInstrumentReference,
    TargetListingReference,
    TargetMappingState,
    TargetNode,
    TargetNodeKind,
    target_content_digest,
)
from trading212_domain.targets import (
    TargetConstraintKind as Kind,
)

EUR = CurrencyCode("EUR")
AT = datetime(2026, 9, 7, tzinfo=UTC)


def uid(number: int) -> str:
    return str(UUID(int=number))


def planning_input(
    values: tuple[str, ...] = ("60", "40"),
    targets: tuple[str, ...] = ("0.5", "0.5"),
    contribution: str = "20",
    *,
    increments: tuple[str, ...] | None = None,
    cash: str = "0",
    cash_target: str = "0",
    mode: PlanningMode = PlanningMode.GLOBAL,
    grouped: bool = False,
) -> PlanningInput:
    with localcontext(Context(prec=160)):
        nodes = tuple(
            TargetNode(
                chr(65 + i),
                "G" if grouped else None,
                TargetNodeKind.HOLDING,
                chr(65 + i),
                i,
                Decimal(weight),
                TargetHoldingMapping(
                    TargetMappingState.RESOLVED, UUID(int=100 + i), UUID(int=200 + i)
                ),
            )
            for i, weight in enumerate(targets)
        )
        if grouped:
            nodes += (TargetNode("G", None, TargetNodeKind.GROUP, "Group", 0, Decimal(1)),)
        if Decimal(cash_target):
            nodes += (
                TargetNode("cash", None, TargetNodeKind.CASH, "Cash", 255, Decimal(cash_target)),
            )
        constraints = tuple(
            TargetConstraint(
                "step-" + node.key,
                Kind.AMOUNT_INCREMENT,
                node.key,
                amount=Decimal(increments[i] if increments else "1"),
                currency=EUR,
            )
            for i, node in enumerate(nodes)
            if node.kind is TargetNodeKind.HOLDING
        )
        content = TargetContent(nodes, constraints)
        identities = tuple(
            PlanningNodeIdentity(
                uid(300 + i),
                node.key,
                uid(500 + i) if node.kind is TargetNodeKind.HOLDING else None,
            )
            for i, node in enumerate(nodes)
        )
        catalog = TargetCatalog(
            tuple(TargetInstrumentReference(UUID(int=100 + i)) for i in range(len(values))),
            tuple(
                TargetListingReference(UUID(int=200 + i), UUID(int=100 + i))
                for i in range(len(values))
            ),
        )
        valuation = ValuationInput(
            uid(1),
            uid(2),
            EUR,
            AT,
            AT,
            "a" * 64,
            tuple(
                ValuationPosition(
                    uid(200 + i), uid(100 + i), Money(Decimal(amount), EUR), QualityState.FRESH
                )
                for i, amount in enumerate(values)
            ),
            (ValuationCash(Money(Decimal(cash), EUR), QualityState.FRESH),),
            Money(sum((Decimal(x) for x in values), Decimal(cash)), EUR),
            QualityState.FRESH,
            True,
            True,
            sources=(PlanningSource("portfolio_snapshot", uid(1), "a" * 64, "1", AT, AT),),
        )
        options = PlanningOptions(
            Money(Decimal(contribution), EUR),
            mode,
            restricted_group_ids=(identities[-1].id,) if mode is PlanningMode.RESTRICTED else (),
        )
        return PlanningInput(
            valuation,
            uid(3),
            uid(4),
            target_content_digest(content, reporting_currency=EUR, effective_at=AT),
            AT,
            AT,
            content,
            identities,
            catalog,
            options,
        )


def with_content(value: PlanningInput, content: TargetContent) -> PlanningInput:
    old = {x.key: x for x in value.node_identities}
    return replace(
        value,
        target_content=content,
        node_identities=tuple(
            old.get(
                node.key,
                PlanningNodeIdentity(
                    uid(10000 + i),
                    node.key,
                    uid(11000 + i) if node.kind is TargetNodeKind.HOLDING else None,
                ),
            )
            for i, node in enumerate(content.nodes)
        ),
        target_content_digest=target_content_digest(
            content,
            reporting_currency=value.valuation.reporting_currency,
            effective_at=value.target_effective_at,
        ),
    )


def oracle_input(case: dict[str, Any]) -> PlanningInput:
    mode = PlanningMode(case["mode"])
    value = planning_input(
        tuple(case["values"]),
        tuple(case["targets"]),
        case["contribution"],
        increments=tuple(case["increments"]),
        cash=case["current_cash"],
        cash_target=case["cash_target"],
        mode=mode,
        grouped=mode is PlanningMode.RESTRICTED,
    )
    if "hierarchy" in case:
        nodes = list(value.target_content.nodes)
        for ordinal, group in enumerate(case["hierarchy"]["groups"]):
            nodes.append(
                TargetNode(
                    group["key"],
                    None,
                    TargetNodeKind.GROUP,
                    group["key"],
                    ordinal,
                    Decimal(group["target"]),
                )
            )
            for index, weight in zip(group["indices"], group["sibling_weights"], strict=True):
                nodes[index] = replace(
                    nodes[index], parent_key=group["key"], weight=Decimal(weight)
                )
        value = with_content(value, replace(value.target_content, nodes=tuple(nodes)))
    constraints = list(value.target_content.constraints)
    config = case["constraints"]
    for field, kind in (
        ("minimum_funded", Kind.MINIMUM_FUNDED_AMOUNT),
        ("maximum_post_weight", Kind.MAXIMUM_POST_WEIGHT),
    ):
        for row in config.get(field, ()):
            key = chr(65 + row["index"])
            constraints.append(
                TargetConstraint(
                    field + key,
                    kind,
                    key,
                    amount=Decimal(row["amount"]) if "amount" in row else None,
                    currency=EUR if "amount" in row else None,
                    weight=Decimal(row["weight"]) if "weight" in row else None,
                )
            )
    if "cash_reserve_amount" in config or "cash_reserve_weight" in config:
        constraints.append(
            TargetConstraint(
                "reserve",
                Kind.CASH_RESERVE,
                amount=Decimal(config["cash_reserve_amount"])
                if "cash_reserve_amount" in config
                else None,
                currency=EUR if "cash_reserve_amount" in config else None,
                weight=Decimal(config["cash_reserve_weight"])
                if "cash_reserve_weight" in config
                else None,
            )
        )
    value = with_content(value, replace(value.target_content, constraints=tuple(constraints)))
    return replace(
        value,
        options=replace(
            value.options,
            monetary_quantum=Decimal(case["monetary_quantum"]),
            excluded_holding_ids=tuple(uid(500 + i) for i in config.get("excluded_indices", ())),
        ),
    )
