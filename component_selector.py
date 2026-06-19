from typing import Any, Type, TypeVar
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

class ComponentSelectionError(Exception):
    """Агент не смог выбрать валидный компонент за отведённое число попыток."""

def select_component(
    agent: Any,
    schema: Type[T],
    input_text: str,
    *,
    validation_context: dict | None = None,
    max_retries: int = 3,
) -> T:
    """
    Универсальный цикл подбора одного компонента:
    agent.run -> parse json -> validate по schema.
    При ошибке формирует новый промпт с описанием проблемы для агента
    и повторяет, максимум max_retries раз.

    validation_context передаётся в schema.model_validate(..., context=...) —
    туда кладутся вещи типа price_bounds, которые не должны быть
    зашиты статически в саму Pydantic-модель.
    """
    last_error: Exception | None = None
    current_input = input_text

    for attempt in range(1, max_retries + 1):
        raw_output = agent.run(current_input)

        try:
            return schema.model_validate(raw_output, context=validation_context)
        except ValidationError as e:
            last_error = e
            current_input = (
                f"format: {e.errors()}\n"
                f"Исходный запрос:\n{input_text}"
            )
        except Exception as e:
            last_error = e
            current_input = (
                f"Не удалось распарсить ответ ({e}). "
                f"Верни строго валидный JSON по схеме.\n{input_text}"
            )

    raise ComponentSelectionError(
        f"Агент {getattr(agent, 'name', '?')} не выбрал валидный компонент "
        f"за {max_retries} попыток. Последняя ошибка: {last_error}"
    )


