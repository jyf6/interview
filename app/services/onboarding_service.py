from app.data.onboarding_guide import ONBOARDING_GUIDE
from app.schemas.interview import OnboardingGuideResponse


class OnboardingService:
    def build_guide(self) -> OnboardingGuideResponse:
        return OnboardingGuideResponse.model_validate(ONBOARDING_GUIDE)
