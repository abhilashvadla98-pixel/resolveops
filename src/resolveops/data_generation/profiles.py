from dataclasses import dataclass, replace


@dataclass(frozen=True)
class GenerationProfile:
    name: str
    customer_cases: int
    it_requests: int
    seed: int = 20260929
    anomaly_rate: float = 0.35

    def with_overrides(
        self,
        *,
        customer_cases: int | None = None,
        it_requests: int | None = None,
        seed: int | None = None,
        anomaly_rate: float | None = None,
    ) -> "GenerationProfile":
        updated = replace(
            self,
            customer_cases=customer_cases if customer_cases is not None else self.customer_cases,
            it_requests=it_requests if it_requests is not None else self.it_requests,
            seed=seed if seed is not None else self.seed,
            anomaly_rate=anomaly_rate if anomaly_rate is not None else self.anomaly_rate,
        )
        if updated.customer_cases < 1 or updated.it_requests < 1:
            raise ValueError("customer_cases and it_requests must be positive")
        if not 0 <= updated.anomaly_rate <= 1:
            raise ValueError("anomaly_rate must be between 0 and 1")
        return updated


PROFILES: dict[str, GenerationProfile] = {
    "demo": GenerationProfile("demo", customer_cases=18, it_requests=8),
    "small": GenerationProfile("small", customer_cases=1_000, it_requests=250),
    "medium": GenerationProfile("medium", customer_cases=10_000, it_requests=2_500),
    "large": GenerationProfile("large", customer_cases=50_000, it_requests=12_500),
}


def get_profile(name: str) -> GenerationProfile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        choices = ", ".join(sorted(PROFILES))
        raise ValueError(f"unknown profile {name!r}; choose one of: {choices}") from exc
