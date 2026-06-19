from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class BuildContext:
    """
    Состояние одной сборки ПК. Создаётся один раз после init-агента
    и передаётся во все последующие шаги подбора компонентов вместо
    отдельных budget/task/res/ddr аргументов.
    """

    budget: float
    task: str
    resolution: int
    ddr: str

    # выбранные компоненты: {"GPU": GPU(...), "CPU": CPU(...), ...}
    components: dict[str, Any] = field(default_factory=dict)

    def add(self, name: str, component: Any) -> None:
        self.components[name] = component

    def get(self, name: str) -> Optional[Any]:
        return self.components.get(name)

    @property
    def spent(self) -> float:
        return sum(getattr(c, "price_rub", 0.0) for c in self.components.values())

    @property
    def remaining(self) -> float:
        return self.budget - self.spent

    def price_bounds(self, ratio: tuple[float, float]) -> tuple[float, float]:
        return self.budget * ratio[0], self.budget * ratio[1]