import logging

from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.interface.repositories.i_review_repo import IReviewRepository
from backend.app.interface.repositories.i_stadium_repo import IStadiumRepository
from backend.app.models import User
from backend.app.models.auth import Msg
from backend.app.models.stadium_reviews import CreateReview, UpdateReview
from backend.app.services.utils_service.permission import PermissionService
from backend.app.services.decorators import HttpExceptionWrapper
from backend.app.services.redis import RedisClient


logger = logging.getLogger(__name__)

class ReviewService:
    def __init__(self,stadium_repository: IStadiumRepository, review_repository: IReviewRepository, permission: PermissionService, redis: RedisClient):
        self.stadium_repository = stadium_repository
        self.review_repository = review_repository
        self.permission = permission
        self.redis = redis

    @HttpExceptionWrapper
    async def create_review(self, db: AsyncSession, schema: CreateReview, stadium_id: int, user: User):
        stadium = await self.stadium_repository.get_or_404(db=db, object_id=stadium_id)
        if await self.review_repository.check_duplicate_review(db=db, user_id=user.id, stadium_id=stadium_id):
            raise HTTPException(status_code=400, detail="Вы уже оставили отзыв для этого стадиона")
        review = await self.review_repository.create(db=db, schema=schema, stadium_id=stadium.id, user_id=user.id)
        logger.info(f"отзыв {review.id} успешно создан пользователем {user.id}")
        return review

    @HttpExceptionWrapper
    async def update_review(self, db: AsyncSession, schema: UpdateReview, review_id: int, user: User):
        review = await self.review_repository.get_or_404(db=db, object_id=review_id)
        self.permission.check_owner_or_admin(current_user=user, model=review)
        review = await self.review_repository.update(db=db, model=review, schema=schema)
        logger.info(f"отзыв {review_id} успешно обновлен пользователем {user.id}")
        return review

    @HttpExceptionWrapper
    async def delete_review(self, db: AsyncSession, user: User, review_id: int):
        review = await self.review_repository.get_or_404(db=db, object_id=review_id)
        self.permission.check_owner_or_admin(current_user=user, model=review)
        await self.review_repository.remove(db=db, id=review.id)
        logger.info(f"отзыв {review_id} успешно удален пользователем {user.id}")
        return Msg(msg="отзыв успешно удален")
