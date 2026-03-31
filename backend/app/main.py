from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.camera import router as camera_router
from app.api.routes.health import router as health_router
from app.api.routes.robot import router as robot_router
from app.api.routes.syringe import router as syringe_router
from app.core.config import ALLOWED_ORIGIN_REGEX, ALLOWED_ORIGINS, APP_NAME, APP_VERSION

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="Local control API for a Raspberry Pi robot controller.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(robot_router)
app.include_router(camera_router)
app.include_router(syringe_router)
