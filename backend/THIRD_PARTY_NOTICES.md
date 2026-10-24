# Компоненты backend

Сторонний шаблон или исходники другого кредитного приложения не копировались.
Используются установленные библиотеки; точные версии и хеши находятся в
`requirements.txt`, `requirements-dev.txt`, `requirements-postgres-test.txt`.
Лицензии распространяемых пакетов остаются внутри установленных дистрибутивов.

| Компонент | Назначение | Лицензия / источник |
| --- | --- | --- |
| Python | Runtime | PSF, https://www.python.org/ |
| FastAPI / Pydantic / pydantic-settings | API и схемы | MIT, официальные проекты на PyPI |
| Starlette | ASGI-основа | BSD-3-Clause, https://github.com/Kludex/starlette |
| SQLAlchemy / Alembic | ORM и миграции | MIT, https://www.sqlalchemy.org/ |
| psycopg / psycopg-binary | Драйвер PostgreSQL | LGPL-3.0, https://www.psycopg.org/ |
| PostgreSQL | База данных | PostgreSQL License, https://www.postgresql.org/ |
| Uvicorn | HTTP-сервер | BSD-3-Clause, https://www.uvicorn.org/ |
| pwdlib / argon2-cffi | Хеширование паролей | MIT, официальные проекты на PyPI |
| PyJWT | Подпись и проверка токенов | MIT, https://pyjwt.readthedocs.io/ |
| python-multipart | Разбор формы входа | Apache-2.0, https://github.com/Kludex/python-multipart |
| pytest / httpx / Ruff / PyYAML | Только разработка и тесты | MIT, официальные проекты на PyPI |
| pgserver | Только временный PostgreSQL в локальных тестах | https://github.com/orm011/pgserver; метаданные и лицензии поставляются с wheel |

Транзитивные библиотеки перечислены в lock-файлах вместе с источниками
зависимостей. Для полного перечня лицензионных файлов проверяйте dist-info
установленных пакетов; таблица выше перечисляет основные компоненты.

Документация, использованная при реализации:

- https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/
- https://docs.sqlalchemy.org/en/20/orm/versioning.html
- https://pypi.org/project/pgserver/

Данные клиентов и компаний созданы специально для демонстрации. Провайдеры
БКИ и Compliance, записи контрольных перечней и UW blacklist/whitelist —
собственная синтетическая реализация проекта, не сторонний продукт и не
реальная проверка. Backend не использует облачные AI API и не требует внешних
платных API или датасетов. По отдельному запросу сотрудника он может обратиться
к локальному экземпляру Ollama; используемые веса Qwen3-4B-Instruct-2507 Q4_K_M
хранятся в репозитории как Git LFS-объекты, распространяются по Apache-2.0 и
импортируются в Ollama отдельной командой. Ollama и её хранилище моделей не
входят в backend Docker-образ и не нужны для основного кредитного конвейера.
Порядок установки описан в корневом [README](../README.md) и
[инструкции Ollama](../ai-docs/ollama-ai-analysis.md). Ограничения и фикстуры
синтетических проверок описаны в `README.md`.
