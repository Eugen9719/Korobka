import logging
from datetime import datetime
from typing import List

import sentry_sdk
from fastapi import HTTPException, UploadFile, File
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.abstractions.storage import ImageHandler
from backend.app.models import User
from backend.app.models.additional_facility import StadiumFacilityDelete

from backend.app.models.auth import Msg
from backend.app.models.base_model_public import AdditionalFacilityReadBase

from backend.app.models.stadiums import StadiumVerificationUpdate, StadiumStatus, StadiumsCreate, StadiumsUpdate, StadiumsRead, \
    PaginatedStadiumsResponse, Stadium, StadiumReview, StadiumsReadWithFacility, StadiumFacilityCreate, StadiumFacility
from backend.app.repositories.stadiums_repositories import StadiumRepository
from backend.app.services.auth.permission import PermissionService
from backend.app.services.redis import RedisClient

logger = logging.getLogger(__name__)


class StadiumService:
    """Сервис управления пользователями"""

    def __init__(self, stadium_repository: StadiumRepository, permission: PermissionService, redis: RedisClient, image_handler: ImageHandler,
                 ):

        self.stadium_repository = stadium_repository
        self.permission = permission
        self.redis = redis
        self.image_handler = image_handler



    async def create_stadium(self, db: AsyncSession, schema: StadiumsCreate, user: User):
        """
        Создает новый стадион с проверкой уникальности slug.
        """
        if not await self.stadium_repository.is_slug_unique(db, schema.slug):
            logger.warning(f"Слаг '{schema.slug}' уже используется пользователем {user.id}")
            sentry_sdk.capture_message(f"Слаг '{schema.slug}' уже используется пользователем {user.id}", level="warning")
            raise HTTPException(status_code=400, detail="Слаг уже используется")

        stadium = await self.stadium_repository.create_stadium(db, schema, user.id)
        logger.info(f"Стадион создан со слагом: {schema.slug}, пользователь: {user.id}")
        return stadium


    async def update_stadium(self, db: AsyncSession, schema: StadiumsUpdate, stadium_id: int, user: User):
        """
        Обновляет данные стадиона.
        """
        stadium = await self.stadium_repository.get_or_404(db=db, id=stadium_id)
        self.permission.check_owner_or_admin(current_user=user, model=stadium)
        if stadium.status == StadiumStatus.VERIFICATION:
            raise HTTPException(status_code=400, detail="вы не можете изменить объект, пока у него статус 'На верификации'")
        if stadium.slug != schema.slug and not await self.stadium_repository.is_slug_unique(db, schema.slug):
            logger.warning(f"Слаг '{schema.slug}' уже используется пользователем {user.id}")
            sentry_sdk.capture_message(f"Слаг '{schema.slug}' уже используется пользователем {user.id}", level="warning")
            raise HTTPException(status_code=400, detail="Слаг уже используется")


        was_active = stadium.is_active
        stadium = await self.stadium_repository.update_stadium(db=db, model=stadium, schema=schema)
        logger.info(f"Стадион {stadium_id} обновлен пользователем {user.id}", )

        if was_active and not stadium.is_active:
            await self.redis.invalidate_cache("stadiums:all_active", f"Деактивация стадиона {stadium_id}")
        await self.redis.invalidate_cache(f"stadiums:vendor:{user.id}", f"Обновление стадиона {stadium_id}")

        return stadium


    async def delete_stadium(self, db: AsyncSession, user: User, stadium_id: int):
        """
        Удаляет стадион.
        """
        stadium = await self.stadium_repository.get_or_404(db=db, id=stadium_id)
        self.permission.check_owner_or_admin(current_user=user, model=stadium)


        was_active = stadium.is_active
        await self.stadium_repository.delete_stadium(db=db, stadium_id=stadium.id)
        logger.info(f"Стадион {stadium_id} удален пользователем {user.id}")

        if was_active:
            await self.redis.invalidate_cache("stadiums:all_active", f"Удаление стадиона {stadium_id}")

        return Msg(msg="Стадион удален успешно")


    async def verify_stadium(self, db: AsyncSession, schema: StadiumVerificationUpdate, stadium_id: int, user: User):
        """
        Верифицирует стадион.

        :param user: Владелец стадиона
        :param db: Асинхронная сессия базы данных.
        :param schema: Схема с данными для верификации.
        :param stadium_id: ID стадиона.
        :return: Обновленный объект стадиона.
        """
        stadium = await self.stadium_repository.get_or_404(db=db, id=stadium_id)
        self.permission.check_owner_or_admin(current_user=user, model=stadium)
        if stadium.status == StadiumStatus.VERIFICATION:
            raise HTTPException(status_code=400, detail="вы не можете изменить объект, пока у него статус 'На верификации")
        was_active = stadium.is_active
        await self.stadium_repository.update(db=db, model=stadium, schema=schema.model_dump(exclude_unset=True))
        logger.info(f"Cтадион {stadium_id} отправлен на верификацию пользователем {user.id}")

        if was_active and not stadium.is_active:
            await self.redis.invalidate_cache("stadiums:all_active", f"Деактивация стадиона {stadium_id}")
        await self.redis.invalidate_cache(f"stadiums:vendor:{user.id}", f"Обновление стадиона {stadium_id}")
        return stadium


    async def approve_verification_by_admin(self, db: AsyncSession, schema: StadiumVerificationUpdate, stadium_id: int, user: User):
        """
        Подтверждает верификацию стадиона администратором.

        :param user: Суперпользователь
        :param db: Асинхронная сессия базы данных.
        :param schema: Схема с данными для обновления верификации.
        :param stadium_id: ID стадиона.
        :return: Обновленный объект стадиона.
        """
        stadium = await self.stadium_repository.get_or_404(db=db, id=stadium_id)
        is_active = schema.status == StadiumStatus.ADDED
        schema.is_active = is_active
        await self.stadium_repository.update(db=db, model=stadium, schema=schema.model_dump(exclude_unset=True))
        logger.info(f"Верификация стадиона {stadium_id} подтверждена администратором {user.id}")
        if schema.is_active:
            await self.redis.invalidate_cache("stadiums:all_active",
                                              f"Кеш для всех активных стадионов инвалидирован из-за подтверждения верификации стадиона {stadium_id}")
        await self.redis.invalidate_cache(f"stadiums:vendor:{user.id}", f"Обновление стадиона {stadium_id}")
        return stadium


    async def upload_image(self, db: AsyncSession, stadium_id: int, user: User, file: UploadFile = File(...)):
        """
        Загружает изображение для стадиона.
        """
        stadium = await self.stadium_repository.get_or_404(db=db, id=stadium_id)
        if stadium.status == StadiumStatus.VERIFICATION:
            raise HTTPException(status_code=400, detail="вы не можете изменить объект, пока у него статус 'На верификации")
        was_active = stadium.is_active

        await self.image_handler.delete_old_image(db, stadium)
        image = await self.image_handler.upload_image(db=db, instance=stadium, file=file)
        logger.info(f"Изображение загружено для стадиона {stadium_id}")

        if was_active and not stadium.is_active:
            await self.redis.invalidate_cache("stadiums:all_active", f"Загрузка изображения для стадиона {stadium_id}")
        await self.redis.invalidate_cache(f"stadiums:vendor:{user.id}", f"Обновление стадиона {stadium_id}")

        return image


    async def get_stadiums(self, db: AsyncSession, ):
        """
        **Описание:**
        Получает список всех активных стадионов из базы данных.
        **Ответ:**
        - Возвращает список стадионов, каждый из которых содержит информацию о стадионе, включая его название, статус и изображение.
        """
        # Кеш для всех активных стадионов
        cache_key = "stadiums:all_active"

        # Проверяем, есть ли данные в кеше
        cached_stadiums = await self.redis.fetch_cached_data(cache_key=cache_key, schema=StadiumsRead)
        if cached_stadiums:
            return cached_stadiums["items"]  # Возвращаем данные из кеша

        # Если данных нет в кеше, получаем их из базы данных
        stadiums = await self.stadium_repository.get_many(db=db, is_active=True)

        # Подготавливаем данные для кеширования
        json_data = {"items": [stadium.model_dump() for stadium in stadiums]}
        await self.redis.cache_data(cache_key, json_data)  # Кешируем данные

        # Возвращаем данные в формате, ожидаемом в response_model
        return [StadiumsRead(**stadium.model_dump()) for stadium in stadiums]


    async def get_vendor_stadiums(self, db: AsyncSession, user: User, page: int, size: int) -> PaginatedStadiumsResponse:
        # Кеш для стадионов вендора с пагинацией
        cache_key = f"stadiums:vendor:{user.id}:page{page}:size{size}"

        # Пытаемся получить данные из кеша
        cached_data = await self.redis.fetch_cached_data(cache_key=cache_key, schema=Stadium)
        if cached_data:
            return PaginatedStadiumsResponse(**cached_data)

        # Если данных нет в кеше, получаем их из базы данных
        query = select(Stadium).where(Stadium.user_id == user.id)
        paginated_data = await self.stadium_repository.paginate(query, db, page, size)

        # Подготавливаем данные для кеширования
        json_data = {
            "items": [stadium.model_dump() for stadium in paginated_data["items"]],
            "page": paginated_data["page"],
            "pages": paginated_data["pages"]
        }
        await self.redis.cache_data(cache_key, json_data)

        # Возвращаем данные в формате, ожидаемом в response_model
        return PaginatedStadiumsResponse(**paginated_data)

    async def detail_stadium(self, db: AsyncSession, stadium_id: int):
        # Получаем стадион с загруженными связями
        stadium = await self.stadium_repository.get_or_404(
            db=db,
            id=stadium_id,
            options=[
                selectinload(Stadium.stadium_reviews).selectinload(StadiumReview.user_review),
                selectinload(Stadium.stadium_facility)
            ]
        )

        # Формируем список услуг из уже загруженной связи
        facility_response = [
            AdditionalFacilityReadBase(
                id=facility.id,
                name=facility.name,
                svg_image=facility.svg_image,
                description=facility.description,
                price=facility.price
            )
            for facility in stadium.stadium_facility  # Используем уже загруженные данные
        ]

        # Создаем объект StadiumsReadWithServices
        stadium_with_facility = StadiumsReadWithFacility.model_validate(stadium).model_copy(
            update={"stadium_facility": facility_response})

        return stadium_with_facility

    async def add_facility_stadium(self,db: AsyncSession,stadium_id: int,facility_schema: List[StadiumFacilityCreate],user: User) -> dict:
        # 1. Проверяем доступ к стадиону
        stadium = await self.stadium_repository.get_or_404(db, id=stadium_id)
        self.permission.check_owner_or_admin(user, stadium)

        # 2. Проверяем и добавляем сервисы
        added_count = 0
        for facility in facility_schema:
            # 2.1. Проверяем существование сервиса
            if not await self.stadium_repository.service_exists(db, facility.facility_id):
                raise HTTPException(404, f"Сервис с ID {facility.facility_id} не найден")

            # 2.2. Проверяем, что сервис еще не добавлен
            if await self.stadium_repository.is_service_linked(db, stadium_id, facility.facility_id):
                continue

            # 2.3. Добавляем связь
            await self.stadium_repository.link_service_to_stadium(
                db=db,
                stadium_id=stadium_id,
                facility_id=facility.facility_id,
            )
            added_count += 1

        if added_count == 0:
            raise HTTPException(400, "Нет новых сервисов для добавления")

        await db.commit()
        await self.redis.delete_cache_by_prefix("stadiums:")

        return {
            "success": True,
            "added_count": added_count,
            "message": f"Добавлено {added_count} сервисов"
        }


    async def delete_facility_from_stadium(self, db: AsyncSession, schema: StadiumFacilityDelete, user: User):

        stadium = await self.stadium_repository.get_or_404(db, id=schema.stadium_id)
        self.permission.check_owner_or_admin(user, stadium)
        # Находим связь между стадионом и сервисом
        result = await db.execute(
            select(StadiumFacility).where(
                StadiumFacility.stadium_id == schema.stadium_id,
                StadiumFacility.facility_id == schema.facility_id
            )
        )
        # Получаем запись связи
        stadium_facility = result.scalar_one_or_none()
        if not stadium_facility:
            raise HTTPException(status_code=404, detail="Service not found for this stadium")
        # Удаляем связь
        await db.delete(stadium_facility)
        await db.commit()
        logger.info(f"Сервис  id={schema.facility_id} удален со стадиона id={schema.stadium_id}")
        await self.redis.delete_cache_by_prefix("stadiums:")
        return {"detail": "Сервис успешно удален"}



    @staticmethod
    async def get_available_stadiums(self, db: AsyncSession, city: str, start_time: datetime, end_time: datetime) -> List[StadiumsRead]:
        result = self.stadium_repository.search_available_stadiums(db, city, start_time, end_time )
        return result
