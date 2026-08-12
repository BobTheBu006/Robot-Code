from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.env_file import load_env_file

# Machine-specific wiring flags (direction inversion, GPIO tuning) must be in the
# environment before any gantry service reads them.
load_env_file()

from app.api.routes.camera import router as camera_router
from app.api.routes.emergency_stop import router as emergency_stop_router
from app.api.routes.engine import router as engine_router
from app.api.routes.esp32_builder import router as esp32_builder_router
from app.api.routes.functions import router as functions_router
from app.api.routes.hardware_map import router as hardware_map_router
from app.api.routes.health import router as health_router
from app.api.routes.robot import router as robot_router
from app.api.routes.safety import router as safety_router
from app.api.routes.syringe import router as syringe_router
from app.api.routes.workflows import router as workflows_router
from app.services.motor_power import register_safety_hooks
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
app.include_router(safety_router)
app.include_router(emergency_stop_router)
app.include_router(esp32_builder_router)
app.include_router(hardware_map_router)
app.include_router(functions_router)
app.include_router(syringe_router)
app.include_router(workflows_router)
app.include_router(engine_router)

# Motor drivers power down when an E-Stop finishes halting everything.
register_safety_hooks()
