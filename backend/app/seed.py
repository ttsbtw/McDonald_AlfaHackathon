"""Explicit, idempotent local demo seeding; never resets existing records."""
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, text

from .auth import password_hash
from .config import get_settings
from .db import create_database
from .models import Company, CreditProduct, User
from .scoring.contracts import validate_policy


def demo_products():
    for code, name, purpose, max_amount, max_term in (
        ("working_capital", "Оборотные средства — демо", "Закупки и текущие расходы", "5000000.00", 36),
        ("equipment", "Оборудование — демо", "Приобретение оборудования", "10000000.00", 60),
    ):
        policy = {
            "policy_version": f"demo-{code}-2026-10-21-v1", "product_code": code,
            "min_amount": "300000.00", "max_amount": max_amount,
            "min_term_months": 6, "max_term_months": max_term,
            "annual_interest_rate": "24.00", "min_business_age_months": 6,
            "max_debt_burden": "0.70", "max_overdue_days_12m": 30,
            "approve_score": 75, "review_score": 50,
            "required_checks": ["company_registry", "credit_history"],
        }
        validate_policy(policy)
        yield CreditProduct(
            code=code, name=name, description=purpose,
            min_amount=Decimal(policy["min_amount"]), max_amount=Decimal(max_amount),
            min_term_months=6, max_term_months=max_term, annual_interest_rate=Decimal("24.00"),
            rate_note="24% — расчётное допущение демонстрации. Реальная ставка определяется индивидуально.",
            policy_version=policy["policy_version"], scoring_policy=policy,
            source_url="https://alfabank.ru/sme/profits/businesscredit/",
            source_checked_on=date(2026, 10, 21),
            assumptions="Два учебных варианта использования бизнес-кредита. Публичный ориентир для кредита без залога: "
                        "300 тыс.–30 млн рублей. В демо диапазоны сужены; сроки 6–36/60 месяцев, ставка 24% "
                        "и ограничения скоринга выбраны командой и не являются банковским предложением.",
        )


def seed_demo(session, settings):
    passwords = (settings.demo_client_password, settings.demo_second_client_password, settings.demo_employee_password)
    if any(value is None or not 12 <= len(value.get_secret_value()) <= 128 for value in passwords):
        raise ValueError("Set all three DEMO_*_PASSWORD values (12–128 characters) before seeding")
    # Serialize concurrent seed invocations, avoiding duplicate demo users/products.
    session.execute(text("SELECT pg_advisory_xact_lock(73405201)"))
    for index, username, full_name, role, secret in (
        (1, "client1", "Демо-клиент Один", "CLIENT", passwords[0]),
        (2, "client2", "Демо-клиент Два", "CLIENT", passwords[1]),
        (3, "employee", "Демо-сотрудник", "BANK_EMPLOYEE", passwords[2]),
    ):
        user = session.scalar(select(User).where(User.username == username))
        if user is None:
            user = User(id=UUID(int=index), username=username, full_name=full_name, role=role,
                        password_hash=password_hash.hash(secret.get_secret_value()))
            session.add(user)
            session.flush()
        if role == "CLIENT" and user.role == "CLIENT":
            existing = session.scalar(select(Company).where(Company.owner_id == user.id))
            if existing is None:
                session.add(Company(id=UUID(int=100 + index), owner_id=user.id,
                                    name=f"Демо-компания {index}", inn=f"00000000000{index}",
                                    legal_form="IP", registration_date=date(2022, 1, 15)))
    for product in demo_products():
        if session.get(CreditProduct, product.code) is None:
            session.add(product)
    session.commit()


def main():
    settings = get_settings()
    if not settings.seed_demo:
        print("Demo seeding disabled (SEED_DEMO=false).")
        return
    engine, session_factory = create_database(settings)
    try:
        with session_factory() as session:
            seed_demo(session, settings)
        print("Demo records ready; existing records preserved.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
