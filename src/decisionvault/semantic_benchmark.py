from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from decisionvault.domain import DecisionAction, DecisionEpisode, Outcome, Strategy


@dataclass(frozen=True, slots=True)
class SemanticSeed:
    producer_agent_id: str
    situation: str
    strategy: Strategy
    outcome: Outcome
    effectiveness: float
    confidence: float = 1.0
    scope: str = "query"
    age_days: float = 0.0
    supersedes_seed_index: int | None = None
    memory_status: str | None = None


@dataclass(frozen=True, slots=True)
class SemanticCase:
    case_id: str
    family: str
    query: str
    seeds: tuple[SemanticSeed, ...]
    expected_strategy: Strategy | None
    expected_influenced: bool
    expected_action: DecisionAction = DecisionAction.EXECUTE
    expected_resolution: str | None = None
    expected_conflict: bool | None = None
    expected_producer: str | None = None


def production_semantic_cases() -> tuple[SemanticCase, ...]:
    """Hand-authored paraphrase/adversarial cases for the hosted retrieval path.

    These are intentionally not suffix variants of one template. They probe
    semantic retrieval, outcome gating, scope isolation, lifecycle governance,
    and producer diversity using the same strategy contract as the live app.
    """

    shipping = SemanticSeed(
        producer_agent_id="shipping-observer",
        situation=(
            "A parcel was delayed after the destination postal code was entered "
            "incorrectly and the warehouse routing queue needed correction."
        ),
        strategy=Strategy.VERIFY_BILLING_PROFILE,
        outcome=Outcome.SUCCESS,
        effectiveness=0.95,
    )
    password = SemanticSeed(
        producer_agent_id="identity-observer",
        situation=(
            "The user could not sign in because a password reset link had expired; "
            "issuing a new recovery link restored account access."
        ),
        strategy=Strategy.VERIFY_BILLING_PROFILE,
        outcome=Outcome.SUCCESS,
        effectiveness=0.95,
    )

    return (
        SemanticCase(
            case_id="failed-retry-card-reissue",
            family="failed_generic_adaptation",
            query=(
                "A newly issued card works elsewhere, but checkout still appears to "
                "reference the previous card credential and repeated charges are declined."
            ),
            seeds=(
                SemanticSeed(
                    producer_agent_id="payments-observer-a",
                    situation=(
                        "After the customer replaced a physical card, our merchant token "
                        "still represented the old card. Retrying the unchanged charge failed."
                    ),
                    strategy=Strategy.GENERIC_RETRY,
                    outcome=Outcome.FAILED,
                    effectiveness=0.1,
                    confidence=0.95,
                ),
                shipping,
                password,
            ),
            expected_strategy=Strategy.REFRESH_PAYMENT_TOKEN,
            expected_influenced=True,
            expected_producer="payments-observer-a",
        ),
        SemanticCase(
            case_id="failed-retry-wallet-credential",
            family="failed_generic_adaptation",
            query=(
                "The bank reissued the card after fraud. The customer updated the wallet, "
                "yet our saved authorization reference still fails on every checkout attempt."
            ),
            seeds=(
                SemanticSeed(
                    producer_agent_id="payments-observer-b",
                    situation=(
                        "A fraud replacement changed the underlying card credentials. The "
                        "merchant kept retrying a stale stored authorization and each attempt failed."
                    ),
                    strategy=Strategy.GENERIC_RETRY,
                    outcome=Outcome.FAILED,
                    effectiveness=0.05,
                    confidence=0.98,
                ),
                shipping,
                password,
            ),
            expected_strategy=Strategy.REFRESH_PAYMENT_TOKEN,
            expected_influenced=True,
            expected_producer="payments-observer-b",
        ),
        SemanticCase(
            case_id="successful-token-refresh",
            family="successful_refresh_reuse",
            query=(
                "A replacement card is valid, but the merchant's stored credential no longer "
                "authorizes charges. We need the recovery approach that worked on a prior reissue."
            ),
            seeds=(
                SemanticSeed(
                    producer_agent_id="payments-observer-c",
                    situation=(
                        "When a card was reissued, rotating the stored merchant payment token "
                        "to the new credential restored checkout successfully."
                    ),
                    strategy=Strategy.REFRESH_PAYMENT_TOKEN,
                    outcome=Outcome.SUCCESS,
                    effectiveness=0.95,
                    confidence=0.95,
                ),
                shipping,
                password,
            ),
            expected_strategy=Strategy.REFRESH_PAYMENT_TOKEN,
            expected_influenced=True,
            expected_producer="payments-observer-c",
        ),
        SemanticCase(
            case_id="successful-billing-profile",
            family="successful_billing_reuse",
            query=(
                "The issuer rejects the payment after the customer moved home; the billing "
                "address in our profile may no longer match the bank's records."
            ),
            seeds=(
                SemanticSeed(
                    producer_agent_id="billing-observer-a",
                    situation=(
                        "A charge was declined because the postal code and street in the saved "
                        "billing profile differed from issuer records. Correcting the profile fixed it."
                    ),
                    strategy=Strategy.VERIFY_BILLING_PROFILE,
                    outcome=Outcome.SUCCESS,
                    effectiveness=0.92,
                    confidence=0.95,
                ),
                shipping,
                password,
            ),
            expected_strategy=Strategy.VERIFY_BILLING_PROFILE,
            expected_influenced=True,
            expected_producer="billing-observer-a",
        ),
        SemanticCase(
            case_id="low-confidence-failure",
            family="low_confidence_control",
            query=(
                "Checkout still fails after a replacement card and the stored authorization "
                "may be stale, but there is not yet reliable evidence for a recovery action."
            ),
            seeds=(
                SemanticSeed(
                    producer_agent_id="uncertain-observer",
                    situation=(
                        "A retry failed after card replacement, but the observer could not tell "
                        "whether the merchant token or an unrelated issuer issue caused it."
                    ),
                    strategy=Strategy.GENERIC_RETRY,
                    outcome=Outcome.FAILED,
                    effectiveness=0.1,
                    confidence=0.35,
                ),
            ),
            expected_strategy=Strategy.GENERIC_RETRY,
            expected_influenced=False,
        ),
        SemanticCase(
            case_id="weak-success-control",
            family="low_effectiveness_control",
            query=(
                "A billing-address mismatch is suspected on a declined payment, but the prior "
                "profile-verification attempt only produced a weak, inconclusive improvement."
            ),
            seeds=(
                SemanticSeed(
                    producer_agent_id="billing-observer-b",
                    situation=(
                        "Reviewing the billing profile appeared to help once, but the payment "
                        "remained intermittent and the intervention effectiveness was low."
                    ),
                    strategy=Strategy.VERIFY_BILLING_PROFILE,
                    outcome=Outcome.SUCCESS,
                    effectiveness=0.4,
                    confidence=0.95,
                ),
            ),
            expected_strategy=Strategy.GENERIC_RETRY,
            expected_influenced=False,
        ),
        SemanticCase(
            case_id="irrelevant-memory-control",
            family="irrelevant_control",
            query=(
                "A customer replaced a card and now the merchant's saved payment credential "
                "is rejected during checkout."
            ),
            seeds=(shipping, password),
            expected_strategy=Strategy.GENERIC_RETRY,
            expected_influenced=False,
        ),
        SemanticCase(
            case_id="cross-scope-control",
            family="cross_scope_control",
            query=(
                "The stored merchant token points to the old card after reissue and charges fail."
            ),
            seeds=(
                SemanticSeed(
                    producer_agent_id="foreign-payments-observer",
                    situation=(
                        "The stored merchant token points to the old card after reissue and charges fail."
                    ),
                    strategy=Strategy.REFRESH_PAYMENT_TOKEN,
                    outcome=Outcome.SUCCESS,
                    effectiveness=1.0,
                    scope="foreign",
                ),
            ),
            expected_strategy=Strategy.GENERIC_RETRY,
            expected_influenced=False,
        ),
        SemanticCase(
            case_id="balanced-conflict-control",
            family="conflict_control",
            query=(
                "A replacement card cannot complete checkout and refreshing the stored payment "
                "credential is being considered, but agents reported contradictory outcomes."
            ),
            seeds=(
                SemanticSeed(
                    producer_agent_id="payments-observer-success",
                    situation=(
                        "Refreshing the merchant token after card reissue restored checkout."
                    ),
                    strategy=Strategy.REFRESH_PAYMENT_TOKEN,
                    outcome=Outcome.SUCCESS,
                    effectiveness=0.9,
                ),
                SemanticSeed(
                    producer_agent_id="payments-observer-failure",
                    situation=(
                        "Refreshing the merchant token after card reissue did not restore checkout."
                    ),
                    strategy=Strategy.REFRESH_PAYMENT_TOKEN,
                    outcome=Outcome.FAILED,
                    effectiveness=0.1,
                ),
            ),
            expected_strategy=None,
            expected_influenced=False,
            expected_action=DecisionAction.ABSTAIN,
            expected_resolution="CONFLICT_ABSTAIN",
            expected_conflict=True,
        ),
        SemanticCase(
            case_id="stale-memory-control",
            family="stale_control",
            query=(
                "The issuer now rejects checkout because the billing address may differ from "
                "current bank records."
            ),
            seeds=(
                SemanticSeed(
                    producer_agent_id="old-billing-observer",
                    situation=(
                        "Correcting a mismatched billing address restored payment authorization."
                    ),
                    strategy=Strategy.VERIFY_BILLING_PROFILE,
                    outcome=Outcome.SUCCESS,
                    effectiveness=0.95,
                    age_days=120,
                ),
            ),
            expected_strategy=Strategy.GENERIC_RETRY,
            expected_influenced=False,
        ),
        SemanticCase(
            case_id="supersession-control",
            family="supersession_control",
            query=(
                "A replacement card is valid but the merchant credential is obsolete; use the "
                "most recent corrected recovery evidence."
            ),
            seeds=(
                SemanticSeed(
                    producer_agent_id="payments-corrector",
                    situation=(
                        "An earlier investigation blamed a billing-profile mismatch."
                    ),
                    strategy=Strategy.VERIFY_BILLING_PROFILE,
                    outcome=Outcome.SUCCESS,
                    effectiveness=0.9,
                    age_days=1,
                ),
                SemanticSeed(
                    producer_agent_id="payments-corrector",
                    situation=(
                        "Later evidence showed the card reissue invalidated the merchant token; "
                        "refreshing that token restored payment."
                    ),
                    strategy=Strategy.REFRESH_PAYMENT_TOKEN,
                    outcome=Outcome.SUCCESS,
                    effectiveness=0.95,
                    supersedes_seed_index=0,
                ),
            ),
            expected_strategy=Strategy.REFRESH_PAYMENT_TOKEN,
            expected_influenced=True,
            expected_producer="payments-corrector",
        ),
        SemanticCase(
            case_id="duplicate-crowding-control",
            family="candidate_crowding_control",
            query=(
                "A replacement card still fails and two agents disagree on whether repeating the "
                "same generic retry is a valid response."
            ),
            seeds=tuple(
                [
                    SemanticSeed(
                        producer_agent_id="duplicate-observer",
                        situation=(
                            "The replacement card remained declined after repeating the unchanged "
                            f"generic retry; duplicate observation number {index}."
                        ),
                        strategy=Strategy.GENERIC_RETRY,
                        outcome=Outcome.FAILED,
                        effectiveness=0.1,
                    )
                    for index in range(5)
                ]
                + [
                    SemanticSeed(
                        producer_agent_id="independent-observer",
                        situation=(
                            "An independent observer saw the same generic retry succeed after a "
                            "temporary issuer outage cleared."
                        ),
                        strategy=Strategy.GENERIC_RETRY,
                        outcome=Outcome.SUCCESS,
                        effectiveness=0.95,
                    )
                ]
            ),
            expected_strategy=None,
            expected_influenced=False,
            expected_action=DecisionAction.ABSTAIN,
            expected_resolution="CONFLICT_ABSTAIN",
            expected_conflict=True,
        ),
        SemanticCase(
            case_id="distinct-head-conflict-crowding",
            family="candidate_crowding_control",
            query=(
                "A replacement card still cannot complete checkout. Several agents reported "
                "unrelated observations, while two independent payment agents disagree on "
                "whether refreshing the merchant token is effective."
            ),
            seeds=tuple(
                [
                    SemanticSeed(
                        producer_agent_id=f"noise-observer-{index}",
                        situation=(
                            "An unrelated operational observation was logged during the same "
                            f"checkout incident; noise report {index}."
                        ),
                        strategy=Strategy.VERIFY_BILLING_PROFILE,
                        outcome=Outcome.UNKNOWN,
                        effectiveness=0.0,
                    )
                    for index in range(4)
                ]
                + [
                    SemanticSeed(
                        producer_agent_id="refresh-success-observer",
                        situation=(
                            "Refreshing the merchant payment token after a card reissue restored "
                            "checkout successfully."
                        ),
                        strategy=Strategy.REFRESH_PAYMENT_TOKEN,
                        outcome=Outcome.SUCCESS,
                        effectiveness=0.95,
                    ),
                    SemanticSeed(
                        producer_agent_id="refresh-failure-observer",
                        situation=(
                            "Refreshing the merchant payment token after a card reissue failed "
                            "to restore checkout."
                        ),
                        strategy=Strategy.REFRESH_PAYMENT_TOKEN,
                        outcome=Outcome.FAILED,
                        effectiveness=0.1,
                    ),
                ]
            ),
            expected_strategy=None,
            expected_influenced=False,
            expected_action=DecisionAction.ABSTAIN,
            expected_resolution="CONFLICT_ABSTAIN",
            expected_conflict=True,
        ),
        SemanticCase(
            case_id="stale-revoked-crowding",
            family="candidate_crowding_control",
            query=(
                "A reissued card keeps failing because the saved authorization may be stale; "
                "use only current admissible recovery evidence."
            ),
            seeds=tuple(
                [
                    SemanticSeed(
                        producer_agent_id=f"stale-observer-{index}",
                        situation=(
                            "Old payment evidence suggested checking billing details after a "
                            f"decline; stale report {index}."
                        ),
                        strategy=Strategy.VERIFY_BILLING_PROFILE,
                        outcome=Outcome.SUCCESS,
                        effectiveness=0.95,
                        age_days=120,
                    )
                    for index in range(3)
                ]
                + [
                    SemanticSeed(
                        producer_agent_id=f"revoked-observer-{index}",
                        situation=(
                            "A revoked payment-memory entry once recommended checking billing "
                            f"details; revoked report {index}."
                        ),
                        strategy=Strategy.VERIFY_BILLING_PROFILE,
                        outcome=Outcome.SUCCESS,
                        effectiveness=0.95,
                        memory_status="REVOKED",
                    )
                    for index in range(3)
                ]
                + [
                    SemanticSeed(
                        producer_agent_id="fresh-failure-observer",
                        situation=(
                            "Retrying the unchanged saved payment credential after card reissue "
                            "failed again because the token remained stale."
                        ),
                        strategy=Strategy.GENERIC_RETRY,
                        outcome=Outcome.FAILED,
                        effectiveness=0.1,
                    )
                ]
            ),
            expected_strategy=Strategy.REFRESH_PAYMENT_TOKEN,
            expected_influenced=True,
            expected_producer="fresh-failure-observer",
        ),
    )


def seed_episode(
    *,
    episode_id: str,
    scope_id: str,
    seed: SemanticSeed,
    supersedes_episode_id: str | None = None,
    now: datetime | None = None,
) -> DecisionEpisode:
    now = now or datetime.now(timezone.utc)
    evidence = {"producer_agent_id": seed.producer_agent_id}
    if supersedes_episode_id:
        evidence["supersedes_episode_id"] = supersedes_episode_id
    if seed.memory_status:
        evidence["memory_status"] = seed.memory_status
    return DecisionEpisode(
        episode_id=episode_id,
        scope_id=scope_id,
        situation=seed.situation,
        strategy=seed.strategy,
        outcome=seed.outcome,
        effectiveness=seed.effectiveness,
        confidence=seed.confidence,
        evidence=evidence,
        created_at=now - timedelta(days=seed.age_days),
    )
