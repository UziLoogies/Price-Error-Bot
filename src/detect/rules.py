"""Price detection rule definitions."""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional


class RuleType(str, Enum):
    """Types of price detection rules."""

    PERCENT_DROP = "percent_drop"  # current <= baseline * threshold
    ABSOLUTE_THRESHOLD = "absolute"  # current <= threshold
    MSRP_RATIO = "msrp_ratio"  # current <= msrp * threshold
    VELOCITY_CHECK = "velocity"  # price changed N times in M minutes
    PENNY_PRICING = "penny_pricing"  # Price $0.01-$1.00 for high-value products
    CURRENCY_ERROR = "currency_error"  # Currency conversion errors
    VARIANT_DISCREPANCY = "variant_discrepancy"  # Price mismatch across variants
    CATEGORY_OUTLIER = "category_outlier"  # Price >3σ below category average
    MSRP_DEVIATION = "msrp_deviation"  # >90% off MSRP (unless clearance)


@dataclass
class Rule:
    """A price detection rule."""

    id: Optional[int] = None
    name: Optional[str] = None
    rule_type: RuleType = RuleType.PERCENT_DROP
    threshold: Decimal = Decimal("0.3")  # For percent_drop: 0.3 = 70% off
    enabled: bool = True
    priority: int = 0  # Higher priority = checked first

    def check(
        self,
        current_price: Decimal,
        baseline_price: Decimal | None = None,
        msrp: Decimal | None = None,
        previous_price: Decimal | None = None,
    ) -> tuple[bool, str]:
        """
        Check if a price triggers this rule.

        Args:
            current_price: Current price
            baseline_price: Baseline/average price
            msrp: Manufacturer's suggested retail price
            previous_price: Previous price

        Returns:
            Tuple of (triggered: bool, reason: str)
        """
        if not self.enabled:
            return False, "Rule disabled"

        if self.rule_type == RuleType.PERCENT_DROP:
            if baseline_price is None or baseline_price <= 0:
                return False, "No baseline price available"
            if current_price <= baseline_price * self.threshold:
                percent_off = (1 - (current_price / baseline_price)) * 100
                return True, f"{percent_off:.1f}% off baseline (${baseline_price:.2f})"

        elif self.rule_type == RuleType.ABSOLUTE_THRESHOLD:
            if current_price <= self.threshold:
                return True, f"Price ${current_price:.2f} <= threshold ${self.threshold:.2f}"

        elif self.rule_type == RuleType.MSRP_RATIO:
            if msrp is None or msrp <= 0:
                return False, "No MSRP available"
            if current_price <= msrp * self.threshold:
                percent_off_msrp = (1 - (current_price / msrp)) * 100
                return True, f"{percent_off_msrp:.1f}% off MSRP (${msrp:.2f})"

        elif self.rule_type == RuleType.VELOCITY_CHECK:
            # This rule would need price history context
            # For now, we'll implement it in the engine
            return False, "Velocity check requires history context"
        
        elif self.rule_type == RuleType.PENNY_PRICING:
            # Flag items priced $0.01-$1.00 for high-value products
            # Threshold represents minimum expected price for high-value items
            if current_price <= Decimal("1.00") and (msrp or baseline_price):
                expected_price = msrp if msrp else baseline_price
                if expected_price and expected_price >= self.threshold:
                    return True, f"Penny pricing detected: ${current_price:.2f} for item expected ${expected_price:.2f}"
        
        elif self.rule_type == RuleType.CURRENCY_ERROR:
            # Detect currency mismatches (would need currency context)
            # For now, flag suspiciously low prices that might be currency errors
            if msrp and current_price > 0:
                # If price is exactly 1/100th of MSRP, might be currency error
                if abs(current_price - (msrp / 100)) < Decimal("0.01"):
                    return True, f"Possible currency error: ${current_price:.2f} vs MSRP ${msrp:.2f}"
        
        elif self.rule_type == RuleType.MSRP_DEVIATION:
            # Flag >90% off MSRP (unless marked clearance)
            if msrp and msrp > 0:
                discount_ratio = current_price / msrp
                if discount_ratio <= self.threshold:  # threshold = 0.1 (90% off)
                    percent_off = (1 - discount_ratio) * 100
                    return True, f"{percent_off:.1f}% off MSRP (${msrp:.2f}) - potential error"

        return False, "Rule not triggered"

    def to_dict(self) -> dict:
        """Convert rule to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "rule_type": self.rule_type.value,
            "threshold": float(self.threshold),
            "enabled": self.enabled,
            "priority": self.priority,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Rule":
        """Create rule from dictionary."""
        return cls(
            id=data.get("id"),
            name=data.get("name"),
            rule_type=RuleType(data.get("rule_type", "percent_drop")),
            threshold=Decimal(str(data.get("threshold", 0.3))),
            enabled=data.get("enabled", True),
            priority=data.get("priority", 0),
        )
