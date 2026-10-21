# Устройство backend

```mermaid
flowchart LR
    Browser[Swagger / будущий frontend] --> API[FastAPI]
    API --> Auth[Проверка токена и пользователя]
    API --> ORM[SQLAlchemy]
    ORM --> PG[(PostgreSQL)]
    Alembic[Миграции Alembic] --> PG
    Seed[Демоданные] --> PG
```

Все запросы работают в отдельных сессиях БД. Владелец и компания заявки
определяются сервером из вошедшего пользователя. Обновление черновика проверяет
версию в запросе; SQLAlchemy добавляет проверку версии в UPDATE, поэтому две
параллельные записи не могут незаметно затереть друг друга.

```mermaid
erDiagram
    USERS ||--o| COMPANIES : owns
    USERS ||--o{ APPLICATIONS : creates
    COMPANIES ||--o{ APPLICATIONS : belongs_to
    CREDIT_PRODUCTS o|--o{ APPLICATIONS : selected
    USERS {
        uuid id PK
        string username UK
        string password_hash
        string role
        boolean is_active
    }
    COMPANIES {
        uuid id PK
        uuid owner_id FK
        string name
        string inn UK
        string legal_form
        date registration_date
    }
    CREDIT_PRODUCTS {
        string code PK
        numeric min_amount
        numeric max_amount
        int min_term_months
        int max_term_months
        numeric annual_interest_rate
        string policy_version
        jsonb scoring_policy
    }
    APPLICATIONS {
        uuid id PK
        uuid owner_id FK
        uuid company_id FK
        string product_code FK
        string status
        int revision
        numeric requested_amount
        int term_months
        string purpose
        numeric average_monthly_revenue
        numeric average_monthly_operating_expenses
        numeric existing_monthly_debt_payment
        timestamptz created_at
        timestamptz updated_at
    }
```

Составной внешний ключ `(company_id, owner_id)` дополнительно запрещает связать
заявку с компанией другого пользователя даже при ошибке прикладного кода.
Деньги хранятся в NUMERIC(15, 2), даты событий — TIMESTAMPTZ; API нормализует UTC.
JSONB используется только для серверных условий скоринга, не вместо колонок анкеты.

В этой задаче API создаёт только `DRAFT`; иных переходов пока нет. PATCH разрешён
для `DRAFT` и зарезервированного `NEEDS_INFO`. Значения остальных состояний
подготовлены в ограничении БД для следующей задачи, но клиент не может их задать.
Таблицы оценок, событий и решений намеренно не добавлены до реализации обработки.

Модуль `app.scoring` — отдельная чистая функция. Тест совместимости демонстрирует
маппинг анкеты и компании к его контракту. В рабочем HTTP-сценарии этой задачи
скоринг ещё не вызывается: отсутствуют отправка и симуляторы внешних проверок.
