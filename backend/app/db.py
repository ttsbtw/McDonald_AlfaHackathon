from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def create_database(settings):
    engine = create_engine(
        settings.database_url.get_secret_value(), pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )
    return engine, sessionmaker(bind=engine, expire_on_commit=False)
