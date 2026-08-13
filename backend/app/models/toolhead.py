from pydantic import BaseModel, Field

from app.services.toolhead import TOOLHEAD_COUNT


class ToolheadRackGeometry(BaseModel):
    """Physical layout of the tool rack and the tool-change motion.

    Each toolhead carries its own exact X/Y rather than being derived from a base
    and a spacing: the holders are placed by hand, so every slot needs to be
    tunable on its own. Edited values are written back as the new defaults after
    a successful tool change.
    """

    tool_1_x_cm: float = Field(default=0.0, ge=0.0)
    tool_1_y_cm: float = Field(default=2.7, ge=0.0)
    tool_2_x_cm: float = Field(default=0.0, ge=0.0)
    tool_2_y_cm: float = Field(default=12.7, ge=0.0)
    tool_3_x_cm: float = Field(default=0.0, ge=0.0)
    tool_3_y_cm: float = Field(default=22.7, ge=0.0)
    tool_4_x_cm: float = Field(default=0.0, ge=0.0)
    tool_4_y_cm: float = Field(default=32.7, ge=0.0)
    tool_5_x_cm: float = Field(default=0.0, ge=0.0)
    tool_5_y_cm: float = Field(default=42.7, ge=0.0)
    tool_6_x_cm: float = Field(default=0.0, ge=0.0)
    tool_6_y_cm: float = Field(default=52.7, ge=0.0)

    clearance_cm: float = Field(default=2.0, gt=0.0)
    dip_depth_cm: float = Field(default=1.7, gt=0.0)
    lift_cm: float = Field(default=0.1, ge=0.0)
    release_cm: float = Field(default=0.1, ge=0.0)

    def positions(self) -> dict[int, tuple[float, float]]:
        return {
            index: (
                getattr(self, f"tool_{index}_x_cm"),
                getattr(self, f"tool_{index}_y_cm"),
            )
            for index in range(1, TOOLHEAD_COUNT + 1)
        }


class ToolheadPickupRequest(ToolheadRackGeometry):
    tool_port: str | None = None
    toolhead_index: int = Field(default=1, ge=1, le=TOOLHEAD_COUNT)
    approach_speed_rpm: int = Field(default=400, gt=0)
    # On by default: the sequence already drives X to the rack, so the probe
    # is nearly free, and a tool change is where lost steps actually cost
    # something - the head misses its hooks.
    verify_x_home: bool = True



class ToolheadDropRequest(ToolheadRackGeometry):
    tool_port: str | None = None
    approach_speed_rpm: int = Field(default=400, gt=0)
    # On by default: the sequence already drives X to the rack, so the probe
    # is nearly free, and a tool change is where lost steps actually cost
    # something - the head misses its hooks.
    verify_x_home: bool = True

