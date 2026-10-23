# Устройство backend

```mermaid
flowchart LR
    Browser[Кабинеты клиента и сотрудника] --> API[FastAPI]
    API --> Auth[Проверка токена и пользователя]
    API --> Pipeline[app.pipeline: обработка заявки]
    Pipeline --> Checks[app.checks: синтетические BKI и Compliance]
    Pipeline --> Scoring[app.scoring: риск-оценка]
    Pipeline --> UW[app.underwriting: внутренние правила]
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
    APPLICATIONS ||--o{ ASSESSMENTS : assessed_as
    APPLICATIONS ||--o{ APPLICATION_EVENTS : records
    APPLICATIONS ||--o{ AUDIT_LOGS : records
    APPLICATIONS ||--o{ COMPLIANCE_REVIEWS : screened
    APPLICATIONS ||--o{ REVIEW_ACTIONS : reviewed_by
    ASSESSMENTS ||--o{ REVIEW_ACTIONS : used_for
    USERS ||--o{ REVIEW_ACTIONS : decides
    USERS ||--o{ APPLICATION_EVENTS : acts
    USERS o|--o{ AUDIT_LOGS : initiates
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
    ASSESSMENTS {
        uuid id PK
        uuid application_id FK
        int application_revision
        jsonb input_snapshot
        jsonb result
        timestamptz created_at
    }
    APPLICATION_EVENTS {
        uuid id PK
        uuid application_id FK
        uuid actor_id FK
        int application_revision
        string event_type
        string from_status
        string to_status
        text message
        timestamptz created_at
    }
    REVIEW_ACTIONS {
        uuid id PK
        uuid application_id FK
        uuid assessment_id FK
        uuid employee_id FK
        int application_revision
        string action
        text comment
        numeric approved_amount
        int approved_term_months
        numeric annual_interest_rate
        timestamptz created_at
    }
    AUDIT_LOGS {
        uuid id PK
        uuid application_id FK
        string client_identifier
        uuid actor_id FK
        string event_type
        string source
        jsonb payload
        timestamptz created_at
    }
    COMPLIANCE_REVIEWS {
        uuid id PK
        uuid application_id FK
        uuid assessment_id FK
        uuid employee_id FK
        string outcome
        text comment
        timestamptz created_at
    }
```

Составной внешний ключ `(company_id, owner_id)` дополнительно запрещает связать
заявку с компанией другого пользователя даже при ошибке прикладного кода.
Деньги хранятся в NUMERIC(15, 2), даты событий — TIMESTAMPTZ; API нормализует UTC.
JSONB используется только для серверных условий скоринга, не вместо колонок анкеты.

Кредитный конвейер вызывает `checks.bki`, `checks.compliance`, затем
`scoring.assess_application` и `underwriting.evaluate_underwriting`. Он хранит
результат каждой проверки в `audit_logs`, а скоринговый снимок и объяснения — в
`assessments`. Экспорт аудита сотруднику доступен как JSON и CSV.

Клиент создаёт черновики, редактирует их в `DRAFT`/`NEEDS_INFO` и отправляет
полную анкету. Backend сохраняет оценку и переводит заявку в `UNDER_REVIEW`.
Создание, редактирование и отправка атомарно записываются в историю событий.
Повторная подача после `NEEDS_INFO` сохраняет новую оценку отдельно от старых.
Очередь и карточку заявки читает только сотрудник банка; незавершённые черновики
сотруднику не видны. Сотрудник может запросить уточнение, одобрить или отклонить
заявку только по актуальной оценке. Событие перехода, комментарий, оценка и
итоговые условия одобрения сохраняются одной транзакцией.

Удалить заявку клиент может только в `DRAFT`; удаление каскадно убирает её
события. Действия сотрудника записываются отдельно и защищены уникальностью
по редакции оценки.

Модуль `app.scoring` — отдельная чистая функция. При отправке backend передаёт
ему анкету, сведения компании и результаты локальных симуляторов. Каждая оценка
сохраняет входной снимок, результат и редакцию заявки.
