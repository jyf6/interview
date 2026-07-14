from fastapi import Request

from app.services.interview_state_machine import InterviewStateMachine


def get_interview_machine(request: Request) -> InterviewStateMachine:
    return InterviewStateMachine(request.app.state.redis)
