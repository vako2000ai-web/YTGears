"""Deterministic domain model. The host supplies monotonic real seconds."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, localcontext
from enum import StrEnum
from fractions import Fraction
import math

MONEY_MAX = Decimal("79228162514264337593543950335")


def finite(value: float, name: str, minimum=0, maximum=1e12) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"{name}: требуется число")
    value = float(value)
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name}: допустимо {minimum}..{maximum}")
    return value


def integer(value: int, name: str, minimum=0, maximum=2**31 - 1) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name}: требуется целое {minimum}..{maximum}")
    return value


def money(value) -> Decimal:
    # Reject binary float money: JSON is parsed directly into Decimal.
    if isinstance(value, (float, bool)):
        raise ValueError("Сумма USD: используйте Decimal, строку или целое")
    try:
        amount = Decimal(value)
    except (ValueError, TypeError, ArithmeticError) as exc:
        raise ValueError("Некорректная сумма USD") from exc
    if not amount.is_finite() or amount <= 0 or amount > MONEY_MAX or amount.as_tuple().exponent < -28:
        raise ValueError("Сумма USD вне поддерживаемого диапазона Decimal")
    return amount


def add_money(a: Decimal, b: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 80
        result = a + b
    if result > MONEY_MAX:
        raise OverflowError("Общая сумма USD превышает поддерживаемый диапазон")
    return result


@dataclass(frozen=True)
class RoundParameters:
    gear_count: int = 8
    target_seconds: float = 1800

    def __post_init__(self):
        integer(self.gear_count, "N", 2, 4096)
        value = finite(self.target_seconds, "T", 12)
        if value <= 12:
            raise ValueError("T должно быть больше 12 секунд")
        object.__setattr__(self, "target_seconds", value)


class DonationRule(StrEnum):
    SINGLE_BOOST = "SingleBoost"
    WHOLE_DOLLARS_DOUBLING = "WholeDollarsDoubling"


@dataclass(frozen=True)
class SpeedPolicy:
    viewer_slope: float = 0.1
    viewer_transition_seconds: float = 2
    viewer_timeout_seconds: float = 30
    maximum_multiplier: float = 64
    donation_rule: DonationRule = DonationRule.SINGLE_BOOST
    donation_duration_seconds: float | None = None

    def __post_init__(self):
        for name, low, high in (("viewer_slope", 0, 1e6), ("viewer_transition_seconds", 0, 1e12),
                                ("viewer_timeout_seconds", .001, 1e12), ("maximum_multiplier", 2, 1e6)):
            object.__setattr__(self, name, finite(getattr(self, name), name, low, high))
        object.__setattr__(self, "donation_rule", DonationRule(self.donation_rule))
        if self.donation_duration_seconds is not None:
            object.__setattr__(self, "donation_duration_seconds", finite(self.donation_duration_seconds, "donation_duration_seconds", .001))

    def viewers(self, count: int) -> float:
        return min(self.maximum_multiplier, 1 + self.viewer_slope * max(0, count - 1))

    def donations(self, active_usd: Decimal) -> float:
        if active_usd < 1:
            return 1
        if self.donation_rule == DonationRule.SINGLE_BOOST:
            return 2
        return 2 ** min(int(active_usd), math.log2(self.maximum_multiplier))


@dataclass(frozen=True)
class ToothCandidate:
    driver_teeth: int
    driven_teeth: int
    shaft_count: int
    actual_last_period_seconds: float
    relative_time_error: float
    geometry_approved: bool = False

    @property
    def wheel_count(self):
        return 2 * (self.shaft_count - 1)


@dataclass(frozen=True)
class Transmission:
    parameters: RoundParameters
    stage_teeth: tuple[tuple[int, int], ...] | None = None
    periods_seconds: tuple[float, ...] = field(init=False)

    def __post_init__(self):
        n, target = self.parameters.gear_count, self.parameters.target_seconds
        if self.stage_teeth is None:
            periods = [12 * self.total_ratio ** (k / (n - 1)) for k in range(n)]
        else:
            pairs = tuple(tuple(pair) for pair in self.stage_teeth)
            if len(pairs) != n - 1:
                raise ValueError("Число зубчатых пар должно равняться N−1")
            periods = [12.0]
            for driver, driven in pairs:
                integer(driver, "driver_teeth", 12, 120)
                integer(driven, "driven_teeth", 12, 120)
                if driven <= driver:
                    raise ValueError("Каждая ступень должна замедлять")
                periods.append(periods[-1] * driven / driver)
            if not math.isclose(periods[-1], target, rel_tol=1e-12):
                raise ValueError("Зубчатая передача несовместима с T")
            object.__setattr__(self, "stage_teeth", pairs)
        periods[0], periods[-1] = 12.0, target
        object.__setattr__(self, "periods_seconds", tuple(periods))

    @property
    def total_ratio(self):
        return self.parameters.target_seconds / 12

    @property
    def stage_ratio(self):
        return self.total_ratio ** (1 / (self.parameters.gear_count - 1))

    def angle_degrees(self, index: int, mechanism_seconds: float, initial_angle=0) -> float:
        integer(index, "index", 0, self.parameters.gear_count - 1)
        mechanism_seconds = finite(mechanism_seconds, "τ", 0, self.parameters.target_seconds)
        initial_angle = finite(initial_angle, "initial_angle", -1e12)
        return initial_angle + (-1 if index % 2 else 1) * 360 * mechanism_seconds / self.periods_seconds[index]

    def approximate_teeth(self, minimum=12, maximum=120) -> ToothCandidate:
        integer(minimum, "minimum", 12, 4096)
        integer(maximum, "maximum", minimum, 4096)
        _, a, b = min((abs(math.log(min(maximum, max(minimum, round(a * self.stage_ratio))) / a) - math.log(self.stage_ratio)),
                       a, min(maximum, max(minimum, round(a * self.stage_ratio)))) for a in range(minimum, maximum + 1))
        period = 12 * (b / a) ** (self.parameters.gear_count - 1)
        return ToothCandidate(a, b, self.parameters.gear_count, period, period / self.parameters.target_seconds - 1)


def physical_transmission(parameters: RoundParameters) -> Transmission:
    """Find bounded integer teeth, exact total ratio; stages need not be uniform.

    Repeated rational stages plus one correcting stage. Reject unsupported layouts
    rather than drawing meshing teeth with incompatible speeds.
    """
    if parameters.gear_count > 12:
        raise ValueError("В 3D поддерживается от 2 до 12 расчётных валов")
    total = Fraction(str(parameters.target_seconds)) / 12
    stages = parameters.gear_count - 1
    ideal = float(total) ** (1 / stages)
    candidates = {Fraction(b, a) for a in range(12, 121) for b in range(a + 1, 121)}
    def pair(ratio):
        scale = max(1, math.ceil(12 / ratio.denominator))
        a, b = ratio.denominator * scale, ratio.numerator * scale
        return (a, b) if 12 <= a < b <= 120 else None
    for ratio in sorted(candidates, key=lambda v: (abs(math.log(float(v) / ideal)), v.denominator)):
        last = total / ratio ** (stages - 1)
        final = pair(last)
        if final:
            repeated = pair(ratio)
            return Transmission(parameters, (repeated,) * (stages - 1) + (final,))
    raise ValueError("Для N/T не найдена компактная передача 12..120 зубьев. Измените N или T; пример: N=8, T=1800")


class RoundPhase(StrEnum):
    RUNNING = "Running"
    IMPACTED = "Impacted"
    DESTRUCTION = "Destruction"
    RESULTS = "Results"


class DonationStatus(StrEnum):
    ACCEPTED = "Accepted"
    DUPLICATE = "Duplicate"
    CONFLICT = "ConflictingDuplicate"
    UNCONFIRMED = "Unconfirmed"
    CURRENCY = "UnsupportedCurrency"
    WRONG_ROUND = "WrongRound"
    CLOSED = "RoundClosed"


@dataclass(frozen=True)
class Donation:
    round_id: str
    provider: str
    event_id: str
    amount: Decimal
    currency: str = "USD"
    confirmed: bool = True

    def __post_init__(self):
        for name in ("round_id", "provider", "event_id", "currency"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name}: требуется непустая строка")
        if type(self.confirmed) is not bool:
            raise ValueError("confirmed: требуется true/false")
        object.__setattr__(self, "amount", money(self.amount))
        object.__setattr__(self, "currency", self.currency.upper())


@dataclass(frozen=True)
class RoundResult:
    round_id: str
    actual_seconds_to_impact: float
    base_seconds: float
    observed_peak_concurrent_viewers: int | None
    max_viewer_multiplier: float
    max_applied_multiplier: float
    speed_cap_reached: bool
    donation_count: int
    donation_total_usd: Decimal
    viewer_source_available_at_impact: bool
    viewer_data_gap_observed: bool
    unique_viewers: None = None
    unique_accelerating_viewers: None = None
    viewer_metric_status: str = "Недоступно: одновременный онлайн не определяет уникальных зрителей"

    @property
    def saved_seconds(self):
        return self.base_seconds - self.actual_seconds_to_impact


class MechanismRound:
    def __init__(self, round_id: str, parameters=None, policy=None, transmission=None):
        if not isinstance(round_id, str) or not round_id.strip():
            raise ValueError("Требуется round_id")
        self.round_id = round_id
        self.transmission = transmission or Transmission(parameters or RoundParameters())
        self.policy = policy or SpeedPolicy()
        self.phase = RoundPhase.RUNNING
        self.mechanism_seconds = self.elapsed_seconds = 0.0
        self.result = None
        self.impact_count = 0
        self._receipts = {}
        self._active = []
        self._total_usd = self._active_usd = Decimal(0)
        self._viewer_expires = None
        self._viewer = self._target = 1.0
        self._ramp = 0.0
        self._max_viewer = self._max_applied = 1.0
        self._cap_reached = self._data_gap = False
        self._peak = None

    @property
    def progress(self): return self.mechanism_seconds / self.transmission.parameters.target_seconds
    @property
    def viewer_source_available(self): return self._viewer_expires is not None
    @property
    def viewer_multiplier(self): return self._viewer
    @property
    def donation_multiplier(self): return self.policy.donations(self._active_usd)
    @property
    def applied_multiplier(self): return min(self.policy.maximum_multiplier, self._viewer * self.donation_multiplier)
    @property
    def donation_count(self): return len(self._receipts)
    @property
    def donation_total_usd(self): return self._total_usd

    def _target_viewers(self, value):
        if value == self._target: return
        self._target, self._ramp = value, self.policy.viewer_transition_seconds
        if not self._ramp: self._viewer = value

    def observe_viewers(self, count):
        if count is not None: integer(count, "viewers")
        if self.phase != RoundPhase.RUNNING: return False
        if count is None:
            self._viewer_expires, self._data_gap = None, True
            self._target_viewers(1)
        else:
            self._peak = max(self._peak or 0, count)
            self._viewer_expires = self.elapsed_seconds + self.policy.viewer_timeout_seconds
            self._target_viewers(self.policy.viewers(count))
        self._track()
        return True

    def receive_donation(self, donation: Donation):
        if not isinstance(donation, Donation): raise ValueError("Требуется Donation")
        if donation.round_id != self.round_id: return DonationStatus.WRONG_ROUND
        if self.phase != RoundPhase.RUNNING: return DonationStatus.CLOSED
        if not donation.confirmed: return DonationStatus.UNCONFIRMED
        if donation.currency != "USD": return DonationStatus.CURRENCY
        key = donation.provider, donation.event_id
        if key in self._receipts:
            return DonationStatus.DUPLICATE if self._receipts[key] == donation else DonationStatus.CONFLICT
        total, active = add_money(self._total_usd, donation.amount), add_money(self._active_usd, donation.amount)
        expiry = self.elapsed_seconds + self.policy.donation_duration_seconds if self.policy.donation_duration_seconds else math.inf
        self._receipts[key] = donation
        self._active.append((expiry, donation.amount))
        self._total_usd, self._active_usd = total, active
        self._track()
        return DonationStatus.ACCEPTED

    def _expire(self):
        if self._viewer_expires is not None and self._viewer_expires <= self.elapsed_seconds:
            self._viewer_expires, self._data_gap = None, True
            self._target_viewers(1)
        alive = []
        for expiry, amount in self._active:
            if expiry <= self.elapsed_seconds: self._active_usd = add_money(self._active_usd, -amount)
            else: alive.append((expiry, amount))
        self._active = alive

    def _track(self):
        self._max_viewer = max(self._max_viewer, self._viewer)
        self._max_applied = max(self._max_applied, self.applied_multiplier)
        self._cap_reached |= self._viewer * self.donation_multiplier >= self.policy.maximum_multiplier

    def _integral(self, seconds, slope, donation):
        start, rate = self._viewer * donation, slope * donation
        end, cap = start + rate * seconds, self.policy.maximum_multiplier
        if max(start, end) <= cap: return (start + end) * .5 * seconds
        if min(start, end) >= cap: return cap * seconds
        crossing = (cap - start) / rate
        if rate > 0: return (start + cap) * .5 * crossing + cap * (seconds - crossing)
        return cap * crossing + (cap + end) * .5 * (seconds - crossing)

    def advance(self, delta_seconds):
        remaining = finite(delta_seconds, "delta_seconds")
        if self.phase != RoundPhase.RUNNING or not remaining: return False
        while remaining > 0:
            self._expire()
            segment = remaining
            if self._viewer_expires is not None: segment = min(segment, self._viewer_expires - self.elapsed_seconds)
            for expiry, _ in self._active: segment = min(segment, expiry - self.elapsed_seconds)
            if self._ramp > 0: segment = min(segment, self._ramp)
            if not self.viewer_source_available: self._data_gap = True
            slope = (self._target - self._viewer) / self._ramp if self._ramp else 0
            donation = self.donation_multiplier
            distance = self.transmission.parameters.target_seconds - self.mechanism_seconds
            integrated = self._integral(segment, slope, donation)
            impact = integrated >= distance
            consumed = segment
            if impact:
                lo, hi = 0.0, segment
                for _ in range(64):
                    mid = (lo + hi) * .5
                    if self._integral(mid, slope, donation) < distance: lo = mid
                    else: hi = mid
                consumed = hi
            self._track()
            self._viewer += slope * consumed
            self._ramp = max(0.0, self._ramp - consumed)
            if self._ramp == 0: self._viewer = self._target
            self.elapsed_seconds += consumed
            self.mechanism_seconds = self.transmission.parameters.target_seconds if impact else self.mechanism_seconds + integrated
            self._track()
            if impact:
                self.impact_count, self.phase = 1, RoundPhase.IMPACTED
                self.result = RoundResult(self.round_id, self.elapsed_seconds, self.transmission.parameters.target_seconds,
                                          self._peak, self._max_viewer, self._max_applied, self._cap_reached,
                                          len(self._receipts), self._total_usd, self.viewer_source_available,
                                          self._data_gap or self._peak is None)
                return True
            self._expire()
            remaining = max(0.0, remaining - segment)
        return False

    def begin_destruction(self):
        if self.phase != RoundPhase.IMPACTED: return False
        self.phase = RoundPhase.DESTRUCTION
        return True

    def complete_destruction(self):
        if self.phase != RoundPhase.DESTRUCTION: return False
        self.phase = RoundPhase.RESULTS
        return True
