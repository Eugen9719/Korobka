import asyncio
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.users import User
from backend.core.db import engine
from backend.core.security import get_password_hash
from backend.tests.conftest import open_json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Асинхронная функция загрузки данных
async def prepare_local_data(db: AsyncSession):
    try:
        # Загрузка пользователей
        users = open_json("user")
        if not users:
            logger.error("Данные пользователей отсутствуют или не загружены.")
        else:
            for user_data in users:
                raw_password = user_data.get("password")
                if not raw_password:
                    raise ValueError(f"Пароль отсутствует для пользователя {user_data.get('email')}")
                user_data["hashed_password"] = get_password_hash(raw_password)
                user_data.pop("password", None)
                user = User(**user_data)
                db.add(user)
            await db.flush()  # Асинхронный flush для промежуточного сохранения
            await db.commit()  # Асинхронный commit
            logger.info(f"Загружено {len(users)} пользователей.")

        # # Загрузка стадионов
        # stadiums = open_json("1")
        # if not stadiums:
        #     logger.error("Данные полей отсутствуют или не загружены.")
        # else:
        #     for stadiums_data in stadiums:
        #         stadium = Stadium(**stadiums_data)
        #         db.add(stadium)
        #     await db.flush()  # Асинхронный flush для промежуточного сохранения
        #     await db.commit()  # Асинхронный commit
        #     logger.info(f"Загружено {len(stadiums)} полей.")
        #
        # # Загрузка отзывов
        # reviews = open_json("reviews")
        # if not reviews:
        #     logger.error("Данные полей отсутствуют или не загружены.")
        # else:
        #     for review_data in reviews:
        #         review = StadiumReview(**review_data)
        #         db.add(review)
        #     await db.flush()  # Асинхронный flush для промежуточного сохранения
        #     await db.commit()  # Асинхронный commit
        #     logger.info(f"Загружено {len(reviews)} полей.")

    except Exception as e:
        logger.error(f"Ошибка при загрузке данных: {e}")
        await db.rollback()  # Асинхронный rollback
        raise



# Основная функция инициализации
async def init() -> None:
    async with AsyncSession(engine) as session:
        await prepare_local_data(session)  # Не забывайте добавлять await

# Запуск асинхронной функции
if __name__ == "__main__":
    asyncio.run(init())  # Запуск асинхронной функции


    # @pytest.fixture(scope="session", autouse=True)
    # async def prepare_data(db: AsyncSession):
    #     """Подготовка данных перед тестами."""
    #     for table in reversed(SQLModel.metadata.sorted_tables):
    #         await db.execute(table.delete())
    #     await db.commit()
    #
    #     users = [User(**{**u, "hashed_password": get_password_hash(u.pop("password"))}) for u in open_json("user")]
    #     stadiums = [Stadium(**s) for s in open_json("stadiums")]
    #     reviews = [StadiumReview(**r) for r in open_json("reviews")]
    #     bookings = [
    #         Booking(**{**b, "start_time": datetime.fromisoformat(b["start_time"]), "end_time": datetime.fromisoformat(b["end_time"])})
    #         for b in open_json("bookings")
    #     ]
    #
    #     db.add_all(users + stadiums + reviews + bookings)
    #     await db.commit()  # Одна транзакция вместо 4-х
    #
    #     logger.info(f"Загружено {len(users)} пользователей, {len(stadiums)} стадионов, {len(reviews)} отзывов и {len(bookings)} бронирований.")
    #
    #     yield
    #
    #


