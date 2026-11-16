"""Pydantic models: API request/response shapes and the AI analysis schema."""

from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field

MealType = Literal["breakfast", "lunch", "dinner", "snack"]
Sex = Literal["female", "male"]
Activity = Literal["sedentary", "light", "moderate", "active", "very_active"]
Goal = Literal["lose", "maintain", "gain"]
Diet = Literal["any", "vegetarian", "vegan", "eggetarian", "non_vegetarian"]


# ---------- Auth ----------
class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    name: str
    email: str


# ---------- Profile & goals ----------
class Profile(BaseModel):
    sex: Sex = "female"
    age: int = Field(21, ge=10, le=100)
    height_cm: float = Field(160, ge=100, le=250)
    weight_kg: float = Field(55, ge=25, le=300)
    activity_level: Activity = "moderate"
    goal: Goal = "maintain"
    diet_type: Diet = "any"


class Targets(BaseModel):
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    sugar_g: float
    sodium_mg: float
    bmr: float
    tdee: float


# ---------- Nutrition ----------
class Nutrients(BaseModel):
    calories: float = 0
    protein_g: float = 0
    carbs_g: float = 0
    fat_g: float = 0
    fiber_g: float = 0
    sugar_g: float = 0
    sodium_mg: float = 0


class FoodItem(Nutrients):
    name: str
    grams: float


# Schema Claude must fill in for each photo (structured output).
class AIFoodItem(BaseModel):
    name: str = Field(description="Specific dish or food name, e.g. 'Chicken biryani' or 'Boiled egg'")
    portion_description: str = Field(description="Human-readable portion, e.g. '1 cup', '2 rotis', '1 medium bowl'")
    grams: float = Field(description="Estimated edible weight of this item in grams")
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    sugar_g: float
    sodium_mg: float
    confidence: Literal["high", "medium", "low"]


class AIFoodAnalysis(BaseModel):
    is_food: bool = Field(description="False if the photo does not show food or drink")
    meal_name: str = Field(description="Short name for the whole plate, e.g. 'South Indian breakfast'")
    items: list[AIFoodItem]
    health_notes: list[str] = Field(description="1-3 short, practical nutrition observations about this meal")


class AnalysisResult(BaseModel):
    """What the API returns after analysing a photo (before the user saves it)."""
    is_food: bool
    meal_name: str
    items: list[dict]          # AIFoodItem fields
    totals: Nutrients
    health_notes: list[str]
    image_token: str           # temporary id of the uploaded image, used when saving
    source: Literal["claude", "demo"]


class ItemInput(Nutrients):
    """An item the user confirmed. Nutrient fields are the values at `base_grams`;
    the server scales them to the (possibly edited) `grams`."""
    name: str = Field(min_length=1, max_length=80)
    grams: float = Field(gt=0, le=5000)
    base_grams: float = Field(gt=0, le=5000)


class PreviewRequest(BaseModel):
    items: list[ItemInput] = Field(min_length=1, max_length=20)


class SaveMealRequest(PreviewRequest):
    meal_type: MealType
    eaten_at: Optional[str] = None     # ISO date-time; server uses "now" if missing
    note: Optional[str] = Field(None, max_length=300)
    image_token: Optional[str] = Field(None, pattern=r"^[a-f0-9]{32}$")
