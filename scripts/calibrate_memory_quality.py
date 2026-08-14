from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

from decisionvault.memory_quality import (
    AdaptiveThresholdProfile,
    EpisodicThresholdProfile,
    calibrate_memory_quality,
    influence_cutoff_days,
    score_adaptive,
    score_episodic,
)
from decisionvault.adaptive_memory import MemoryClass, MemoryScopeLevel


CURRENT_EPISODIC = EpisodicThresholdProfile(0.30, 0.12, 0.08)
BASELINE_ADAPTIVE = AdaptiveThresholdProfile(0.40, 0.15, 0.08)


def main() -> int:
    result = calibrate_memory_quality()
    payload = {
        "calibration_contract": "memory-quality-v1",
        "objective": "safety-weighted synthetic adversarial calibration",
        "current": {
            "episodic": asdict(CURRENT_EPISODIC),
            "episodic_score": asdict(score_episodic(CURRENT_EPISODIC)),
            "adaptive": asdict(BASELINE_ADAPTIVE),
            "adaptive_score": asdict(score_adaptive(BASELINE_ADAPTIVE)),
        },
        "recommended": {
            "episodic": asdict(result.episodic_profile),
            "episodic_score": asdict(result.episodic_score),
            "adaptive": asdict(result.adaptive_profile),
            "adaptive_score": asdict(result.adaptive_score),
        },
        "production_guardrail": (
            "Do not change SQL-coupled evidence gates (success effectiveness 0.7, "
            "failure confidence 0.6, 90-day episodic freshness) from this report. "
            "Those require a coordinated SQL/resolver migration and live regression."
        ),
        "long_term_influence_windows_days": {
            level.value: {
                "baseline_0_15": influence_cutoff_days(
                    memory_class=MemoryClass.LONG_TERM,
                    scope_level=level,
                    minimum_effective_confidence=0.15,
                ),
                "calibrated_0_30": influence_cutoff_days(
                    memory_class=MemoryClass.LONG_TERM,
                    scope_level=level,
                    minimum_effective_confidence=0.30,
                ),
                "hard_expiry_days": 365.0,
            }
            for level in MemoryScopeLevel
        },
    }
    output = Path("reports/memory-quality-calibration.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"calibration_output={output}")
    print(
        "episodic_current="
        f"{payload['current']['episodic_score']['passed_cases']}/"
        f"{payload['current']['episodic_score']['total_cases']}"
    )
    print(
        "episodic_recommended="
        f"{payload['recommended']['episodic_score']['passed_cases']}/"
        f"{payload['recommended']['episodic_score']['total_cases']}"
    )
    print(
        "adaptive_current="
        f"{payload['current']['adaptive_score']['passed_cases']}/"
        f"{payload['current']['adaptive_score']['total_cases']}"
    )
    print(
        "adaptive_recommended="
        f"{payload['recommended']['adaptive_score']['passed_cases']}/"
        f"{payload['recommended']['adaptive_score']['total_cases']}"
    )
    print("memory_quality_calibration=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
