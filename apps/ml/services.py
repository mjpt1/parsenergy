from dataclasses import dataclass
from pathlib import Path
import joblib
import numpy as np
# sklearn/scipy are imported inside the functions that use them. Importing
# them at module level made every app start take long enough on cPanel that
# Passenger killed the worker mid-import and visitors got a 500 after restarts.

MODEL_DIR = Path('media/models')
MODEL_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class PredictionResult:
    forecast_kw: float
    fault_probability: float
    maintenance_score: float


@dataclass
class MaintenanceRecommendation:
    priority: str
    recommendation: str


def build_forecast_model():
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    return Pipeline([
        ('imputer', SimpleImputer(strategy='median')),
        ('scaler', StandardScaler()),
        ('model', RandomForestRegressor(n_estimators=50, random_state=42)),
    ])


def build_fault_model():
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    return Pipeline([
        ('imputer', SimpleImputer(strategy='median')),
        ('model', RandomForestClassifier(n_estimators=50, random_state=42)),
    ])


def train_models(features: np.ndarray, target_kw: np.ndarray, fault_target: np.ndarray):
    from sklearn.model_selection import train_test_split
    X_train, X_test, y_train, y_test = train_test_split(features, target_kw, test_size=0.2, random_state=42)
    forecast_model = build_forecast_model().fit(X_train, y_train)
    fault_model = build_fault_model().fit(features, fault_target)
    joblib.dump(forecast_model, MODEL_DIR / 'forecast.joblib')
    joblib.dump(fault_model, MODEL_DIR / 'fault.joblib')
    return {'forecast_score': forecast_model.score(X_test, y_test)}


def predict_next(features: list[float]) -> PredictionResult:
    x = np.array([features])
    forecast_model_path = MODEL_DIR / 'forecast.joblib'
    fault_model_path = MODEL_DIR / 'fault.joblib'
    if forecast_model_path.exists():
        forecast_model = joblib.load(forecast_model_path)
        forecast_kw = float(forecast_model.predict(x)[0])
    else:
        forecast_kw = float(np.mean(features)) if features else 0.0
    if fault_model_path.exists():
        fault_model = joblib.load(fault_model_path)
        fault_probability = float(max(fault_model.predict_proba(x)[0]))
    else:
        fault_probability = 0.0
    maintenance_score = max(0.0, 1.0 - fault_probability)
    return PredictionResult(forecast_kw=forecast_kw, fault_probability=fault_probability, maintenance_score=maintenance_score)


def recommend_maintenance(result: PredictionResult) -> MaintenanceRecommendation:
    if result.fault_probability >= 0.8:
        return MaintenanceRecommendation(priority='high', recommendation='Immediate inspection and inverter diagnostics required')
    if result.fault_probability >= 0.5:
        return MaintenanceRecommendation(priority='medium', recommendation='Schedule preventive maintenance within 72 hours')
    return MaintenanceRecommendation(priority='low', recommendation='Continue monitoring and keep current maintenance plan')
