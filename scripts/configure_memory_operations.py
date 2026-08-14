from __future__ import annotations

import argparse
import json
from typing import Any


def alarm_definitions(*, function_name: str) -> tuple[dict[str, Any], ...]:
    common = {
        "Namespace": "DecisionVault",
        "Period": 300,
        "EvaluationPeriods": 1,
        "TreatMissingData": "notBreaching",
        "ActionsEnabled": True,
    }
    return (
        {
            **common,
            "AlarmName": f"{function_name}-consolidation-deferred",
            "MetricName": "ConsolidationDeferredCount",
            "Statistic": "Sum",
            "Threshold": 1.0,
            "ComparisonOperator": "GreaterThanOrEqualToThreshold",
            "Dimensions": [
                {"Name": "MemoryEvent", "Value": "consolidation_deferred"}
            ],
        },
        {
            **common,
            "AlarmName": f"{function_name}-secret-refresh-failure",
            "MetricName": "SecretRefreshFailureCount",
            "Statistic": "Sum",
            "Threshold": 1.0,
            "ComparisonOperator": "GreaterThanOrEqualToThreshold",
            "Dimensions": [
                {"Name": "MemoryEvent", "Value": "secret_refresh_failure"}
            ],
        },
        {
            **common,
            "AlarmName": f"{function_name}-consolidation-backlog",
            "MetricName": "ConsolidationOutboxBacklog",
            "Statistic": "Maximum",
            "Threshold": 10.0,
            "ComparisonOperator": "GreaterThanOrEqualToThreshold",
            "Dimensions": [
                {"Name": "MemoryEvent", "Value": "consolidation_retry_drain"}
            ],
        },
        {
            **common,
            "AlarmName": f"{function_name}-memory-quality-decision-write-failure",
            "MetricName": "MemoryQualityDecisionWriteFailureCount",
            "Statistic": "Sum",
            "Threshold": 1.0,
            "ComparisonOperator": "GreaterThanOrEqualToThreshold",
            "Dimensions": [
                {
                    "Name": "MemoryEvent",
                    "Value": "memory_quality_decision_write_failure",
                }
            ],
        },
        {
            **common,
            "AlarmName": f"{function_name}-memory-quality-outcome-write-failure",
            "MetricName": "MemoryQualityOutcomeWriteFailureCount",
            "Statistic": "Sum",
            "Threshold": 1.0,
            "ComparisonOperator": "GreaterThanOrEqualToThreshold",
            "Dimensions": [
                {
                    "Name": "MemoryEvent",
                    "Value": "memory_quality_outcome_write_failure",
                }
            ],
        },
    )


def dashboard_body(*, function_name: str, region: str) -> str:
    body = {
        "widgets": [
            {
                "type": "metric",
                "width": 12,
                "height": 6,
                "properties": {
                    "title": "DecisionVault request health",
                    "region": region,
                    "period": 300,
                    "metrics": [
                        [
                            {
                                "expression": (
                                    "SEARCH('{DecisionVault,Route} MetricName=\"RequestCount\"', "
                                    "'Sum', 300)"
                                ),
                                "label": "RequestCount",
                                "id": "request_count",
                            }
                        ],
                        [
                            {
                                "expression": (
                                    "SEARCH('{DecisionVault,Route} MetricName=\"ErrorCount\"', "
                                    "'Sum', 300)"
                                ),
                                "label": "ErrorCount",
                                "id": "error_count",
                            }
                        ],
                        ["AWS/Lambda", "Errors", "FunctionName", function_name],
                        [".", "Throttles", ".", "."],
                    ],
                },
            },
            {
                "type": "metric",
                "width": 12,
                "height": 6,
                "properties": {
                    "title": "Governed adaptive-memory health",
                    "region": region,
                    "period": 300,
                    "metrics": [
                        [
                            {
                                "expression": (
                                    "SEARCH('{DecisionVault,MemoryEvent} "
                                    "MetricName=\"ConsolidationCompletedCount\"', 'Sum', 300)"
                                ),
                                "label": "ConsolidationCompletedCount",
                                "id": "consolidation_completed",
                            }
                        ],
                        [
                            {
                                "expression": (
                                    "SEARCH('{DecisionVault,MemoryEvent} "
                                    "MetricName=\"ConsolidationDeferredCount\"', 'Sum', 300)"
                                ),
                                "label": "ConsolidationDeferredCount",
                                "id": "consolidation_deferred",
                            }
                        ],
                        [
                            {
                                "expression": (
                                    "SEARCH('{DecisionVault,MemoryEvent} "
                                    "MetricName=\"GovernedPromotionCount\"', 'Sum', 300)"
                                ),
                                "label": "GovernedPromotionCount",
                                "id": "promotions",
                            }
                        ],
                        [
                            {
                                "expression": (
                                    "SEARCH('{DecisionVault,MemoryEvent} "
                                    "MetricName=\"GovernedAbstentionCount\"', 'Sum', 300)"
                                ),
                                "label": "GovernedAbstentionCount",
                                "id": "abstentions",
                            }
                        ],
                        [
                            {
                                "expression": (
                                    "SEARCH('{DecisionVault,MemoryEvent} "
                                    "MetricName=\"NegativeMemoryVetoCount\"', 'Sum', 300)"
                                ),
                                "label": "NegativeMemoryVetoCount",
                                "id": "negative_veto",
                            }
                        ],
                        [
                            {
                                "expression": (
                                    "SEARCH('{DecisionVault,MemoryEvent} "
                                    "MetricName=\"CrossLayerConflictCount\"', 'Sum', 300)"
                                ),
                                "label": "CrossLayerConflictCount",
                                "id": "cross_layer_conflict",
                            }
                        ],
                        [
                            {
                                "expression": (
                                    "SEARCH('{DecisionVault,MemoryEvent} "
                                    "MetricName=\"ProducerRetiredCount\"', 'Sum', 300)"
                                ),
                                "label": "ProducerRetiredCount",
                                "id": "producer_retired",
                            }
                        ],
                        [
                            {
                                "expression": (
                                    "SEARCH('{DecisionVault,MemoryEvent} "
                                    "MetricName=\"SecretRefreshFailureCount\"', 'Sum', 300)"
                                ),
                                "label": "SecretRefreshFailureCount",
                                "id": "secret_refresh_failure",
                            }
                        ],
                    ],
                },
            },
            {
                "type": "metric",
                "width": 12,
                "height": 6,
                "properties": {
                    "title": "Consolidation backlog",
                    "region": region,
                    "period": 300,
                    "metrics": [
                        [
                            {
                                "expression": (
                                    "SEARCH('{DecisionVault,MemoryEvent} "
                                    "MetricName=\"ConsolidationOutboxBacklog\"', 'Maximum', 300)"
                                ),
                                "label": "ConsolidationOutboxBacklog",
                                "id": "outbox_backlog",
                            }
                        ],
                    ],
                },
            },
            {
                "type": "metric",
                "width": 12,
                "height": 6,
                "properties": {
                    "title": "Adaptive-memory use",
                    "region": region,
                    "period": 300,
                    "metrics": [
                        [
                            {
                                "expression": (
                                    "SEARCH('{DecisionVault,MemoryEvent} "
                                    "MetricName=\"AdaptiveMemoryHitCount\"', 'Sum', 300)"
                                ),
                                "label": "AdaptiveMemoryHitCount",
                                "id": "adaptive_hit",
                            }
                        ],
                        [
                            {
                                "expression": (
                                    "SEARCH('{DecisionVault,Route} "
                                    "MetricName=\"MemoryInfluencedCount\"', 'Sum', 300)"
                                ),
                                "label": "MemoryInfluencedCount",
                                "id": "memory_influenced",
                            }
                        ],
                        [
                            {
                                "expression": (
                                    "SEARCH('{DecisionVault,Route} "
                                    "MetricName=\"MemoryConflictCount\"', 'Sum', 300)"
                                ),
                                "label": "MemoryConflictCount",
                                "id": "memory_conflict",
                            }
                        ],
                    ],
                },
            },
            {
                "type": "metric",
                "width": 12,
                "height": 6,
                "properties": {
                    "title": "Memory-quality telemetry",
                    "region": region,
                    "period": 300,
                    "metrics": [
                        [
                            {
                                "expression": (
                                    "SEARCH('{DecisionVault,MemoryEvent} "
                                    "MetricName=\"MemoryQualityDecisionObservedCount\"', "
                                    "'Sum', 300)"
                                ),
                                "label": "Decision telemetry",
                                "id": "quality_decisions",
                            }
                        ],
                        [
                            {
                                "expression": (
                                    "SEARCH('{DecisionVault,MemoryEvent} "
                                    "MetricName=\"MemoryQualityOutcomeObservedCount\"', "
                                    "'Sum', 300)"
                                ),
                                "label": "Verified outcome telemetry",
                                "id": "quality_outcomes",
                            }
                        ],
                        [
                            {
                                "expression": (
                                    "SEARCH('{DecisionVault,MemoryEvent} "
                                    "MetricName=\"MemoryQualityDecisionWriteFailureCount\"', "
                                    "'Sum', 300)"
                                ),
                                "label": "Decision write failures",
                                "id": "quality_decision_failures",
                            }
                        ],
                        [
                            {
                                "expression": (
                                    "SEARCH('{DecisionVault,MemoryEvent} "
                                    "MetricName=\"MemoryQualityOutcomeWriteFailureCount\"', "
                                    "'Sum', 300)"
                                ),
                                "label": "Outcome write failures",
                                "id": "quality_outcome_failures",
                            }
                        ],
                    ],
                },
            },
        ]
    }
    return json.dumps(body, separators=(",", ":"), sort_keys=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Configure DecisionVault's durable consolidation retry schedule, "
            "memory-health alarms, and CloudWatch dashboard."
        )
    )
    parser.add_argument("--function-name", default="decisionvault-agent")
    parser.add_argument("--region", default="ap-northeast-1")
    parser.add_argument("--schedule-minutes", type=int, default=5)
    args = parser.parse_args()
    if args.schedule_minutes < 1:
        raise SystemExit("--schedule-minutes must be >= 1")

    import boto3

    session = boto3.Session(region_name=args.region)
    lambda_client = session.client("lambda")
    events = session.client("events")
    cloudwatch = session.client("cloudwatch")

    function = lambda_client.get_function(FunctionName=args.function_name)
    function_arn = function["Configuration"]["FunctionArn"]
    rule_name = f"{args.function_name}-consolidation-retry"
    rule = events.put_rule(
        Name=rule_name,
        ScheduleExpression=f"rate({args.schedule_minutes} minutes)",
        State="ENABLED",
        Description="Retry DecisionVault governed adaptive-memory consolidation backlog",
    )
    rule_arn = rule["RuleArn"]
    events.put_targets(
        Rule=rule_name,
        Targets=[
            {
                "Id": "decisionvault-consolidation-retry",
                "Arn": function_arn,
            }
        ],
    )
    try:
        lambda_client.add_permission(
            FunctionName=args.function_name,
            StatementId="decisionvault-consolidation-retry",
            Action="lambda:InvokeFunction",
            Principal="events.amazonaws.com",
            SourceArn=rule_arn,
        )
    except lambda_client.exceptions.ResourceConflictException:
        pass

    for alarm in alarm_definitions(function_name=args.function_name):
        cloudwatch.put_metric_alarm(**alarm)

    dashboard_name = f"{args.function_name}-memory-operations"
    cloudwatch.put_dashboard(
        DashboardName=dashboard_name,
        DashboardBody=dashboard_body(
            function_name=args.function_name,
            region=args.region,
        ),
    )

    print(f"eventbridge_rule={rule_name}")
    print(f"eventbridge_schedule_minutes={args.schedule_minutes}")
    print(f"cloudwatch_alarms={len(alarm_definitions(function_name=args.function_name))}")
    print(f"cloudwatch_dashboard={dashboard_name}")
    print("memory_operations_configure=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
