"""User profile -> daily nutrition -> meal-level parameters.

Implements the BMR/TDEE chain described in the proposal (Section 3).
"""
from dataclasses import dataclass
from typing import Literal

Sex = Literal["M", "F"]
ActivityLevel = Literal["low", "mid", "high"]
HealthGoal = Literal["maintain", "cut", "bulk"]
ScenarioMode = Literal["light", "regular", "latenight"]

AF_TABLE = {"low": 1.2, "mid": 1.55, "high": 1.725}
PF_TABLE = {"maintain": 1.1, "cut": 1.6, "bulk": 1.8}
FAT_RATIO = {"maintain": (0.20, 0.30), "cut": (0.20, 0.25), "bulk": (0.25, 0.30)}
CARB_RATIO = {"maintain": (0.45, 0.65), "cut": (0.35, 0.50), "bulk": (0.50, 0.60)}

# meal-share parameters: (rho_min, rho_max, rho_nominal) and item-count cap
SCENARIO_PARAMS = {
    "light":     {"rho_min": 0.15, "rho_max": 0.25, "rho": 0.20, "Nmax": 3},
    "regular":   {"rho_min": 0.30, "rho_max": 0.45, "rho": 0.40, "Nmax": 5},
    "latenight": {"rho_min": 0.05, "rho_max": 0.15, "rho": 0.10, "Nmax": 3},
}


@dataclass
class UserProfile:
    sex: Sex
    age: int
    height_cm: float
    weight_kg: float
    activity: ActivityLevel
    goal: HealthGoal
    budget: float = 120.0
    scenario: ScenarioMode = "regular"


@dataclass
class DailyTarget:
    cal: float
    protein: float
    fat_min: float
    fat_max: float
    carb_min: float
    carb_max: float
    sugar_max: float
    sodium_max: float


@dataclass
class MealTarget:
    cal_min: float
    cal_max: float
    protein_min: float
    fat_min: float
    fat_max: float
    carb_min: float
    carb_max: float
    sugar_max: float
    sodium_max: float
    n_max: int


def compute_bmr(profile: UserProfile) -> float:
    w, h, a = profile.weight_kg, profile.height_cm, profile.age
    if profile.sex == "M":
        return 10 * w + 6.25 * h - 5 * a + 5
    return 10 * w + 6.25 * h - 5 * a - 161


def compute_daily_target(profile: UserProfile) -> DailyTarget:
    bmr = compute_bmr(profile)
    tdee = bmr * AF_TABLE[profile.activity]
    if profile.goal == "cut":
        target_cal = tdee - 500
    elif profile.goal == "bulk":
        target_cal = tdee + 300
    else:
        target_cal = tdee

    target_pro = profile.weight_kg * PF_TABLE[profile.goal]
    ff_min, ff_max = FAT_RATIO[profile.goal]
    cf_min, cf_max = CARB_RATIO[profile.goal]
    return DailyTarget(
        cal=target_cal,
        protein=target_pro,
        fat_min=target_cal * ff_min / 9.0,
        fat_max=target_cal * ff_max / 9.0,
        carb_min=target_cal * cf_min / 4.0,
        carb_max=target_cal * cf_max / 4.0,
        sugar_max=0.10 * target_cal / 4.0,
        sodium_max=2400.0,
    )


def to_meal_target(daily: DailyTarget, scenario: ScenarioMode) -> MealTarget:
    sp = SCENARIO_PARAMS[scenario]
    rho, rho_min, rho_max = sp["rho"], sp["rho_min"], sp["rho_max"]
    return MealTarget(
        cal_min=daily.cal * rho_min,
        cal_max=daily.cal * rho_max,
        protein_min=daily.protein * rho,
        fat_min=daily.fat_min * rho,
        fat_max=daily.fat_max * rho,
        carb_min=daily.carb_min * rho,
        carb_max=daily.carb_max * rho,
        sugar_max=daily.sugar_max * rho,
        sodium_max=daily.sodium_max * rho,
        n_max=sp["Nmax"],
    )


if __name__ == "__main__":
    u = UserProfile(sex="M", age=22, height_cm=175, weight_kg=70,
                    activity="mid", goal="cut", budget=120, scenario="regular")
    d = compute_daily_target(u)
    m = to_meal_target(d, "regular")
    print("BMR =", round(compute_bmr(u), 1))
    print("Daily:", d)
    print("Meal:", m)
