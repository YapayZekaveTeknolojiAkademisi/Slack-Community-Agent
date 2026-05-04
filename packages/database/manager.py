from __future__ import annotations

from logging import Logger
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from packages.settings import get_settings


_s = get_settings()


class DatabaseManager:
    """
    Logger, ``start_logging`` sonrası ilk kullanımda ``packages.logger.manager.get_logger``
    ile bağlanır (servis girişinde db genelde logger'dan önce import edilir).
    """

    def __init__(self) -> None:
        self._logger_cache: Logger | None = None
        self._engine: AsyncEngine | None = None
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None

    @property
    def _logger(self) -> Logger:
        if self._logger_cache is None:
            from packages.logger.manager import get_logger

            self._logger_cache = get_logger("packages.database")
        return self._logger_cache

    def _create_database_url(self) -> str:
        return f"postgresql+asyncpg://{_s.username}:{_s.password}@{_s.host}:{_s.port}/{_s.database}"

    def initialize(self) -> None:
        if self._engine is not None:
            self._logger.warning("DatabaseManager already initialized")
            return
            
        self._engine = create_async_engine(
            self._create_database_url(),
            echo=False,
            pool_size=_s.db_pool_size,
            max_overflow=_s.db_max_overflow,
            pool_timeout=_s.db_pool_timeout,
            pool_pre_ping=_s.db_pool_pre_ping,
            pool_recycle=_s.db_pool_recycle,
        )

        self._sessionmaker = async_sessionmaker(
            bind=self._engine, 
            expire_on_commit=False, 
            autoflush=False, 
            class_=AsyncSession,
        )

        self._logger.info("SqlAlchemy Engine & Sessionmaker initialized")

    @asynccontextmanager
    async def session(self, read_only: bool = False) -> AsyncGenerator[AsyncSession, None]:
        if self._sessionmaker is None:
            self._logger.error("DatabaseManager not initialized. Call initialize() first.")
            raise RuntimeError("DatabaseManager not initialized. Call initialize() first.")

        async with self._sessionmaker() as session:
            try:
                async with session.begin():
                    if read_only:
                        await session.execute(text("SET TRANSACTION READ ONLY"))
                    yield session
            except Exception as e:
                self._logger.error(f"Error in session: {e}")
                await session.rollback()
                raise

    async def shutdown(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
        self._sessionmaker = None
        self._logger.info("SqlAlchemy Engine & Sessionmaker shutdown")


db = DatabaseManager()
