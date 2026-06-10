"""
产品入场引导处理器。

该模块不依赖会话状态机、不调用 LLM，方便未来独立接入到其他产品页面。
"""

from core.models import OnboardingGuideResponse, OnboardingStep
from config.onboarding_config import ONBOARDING_GUIDE


def get_onboarding_guide() -> OnboardingGuideResponse:
    """返回产品入场引导配置。"""
    steps = sorted(ONBOARDING_GUIDE["steps"], key=lambda item: item["sequence"])
    return OnboardingGuideResponse(
        guide_id=ONBOARDING_GUIDE["guide_id"],
        version=ONBOARDING_GUIDE["version"],
        title=ONBOARDING_GUIDE["title"],
        description=ONBOARDING_GUIDE.get("description", ""),
        target_contract=ONBOARDING_GUIDE.get("target_contract", {}),
        steps=[OnboardingStep(**step) for step in steps],
    )
