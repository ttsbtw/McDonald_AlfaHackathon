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

Данные клиентов и компаний созданы специально для демонстрации. Условия
демопродуктов и источник их публичных ориентиров описаны в README. Внешних
интеграций, платных API, ML-моделей и внешних датасетов в этом backend нет.
Симуляторы реестра и кредитной истории относятся к следующей задаче и пока
не реализованы. Тест совместимости скоринга использует явные синтетические checks.
