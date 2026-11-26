from fastapi import Request

from app.agent.session import AgentSessionManager
from app.experiments.store import ExperimentStore
from app.processes.store import ProcessStore
from app.reliability.store import ReliabilityStore


def get_process_store(request: Request) -> ProcessStore:
    return request.app.state.process_store


def get_reliability_store(request: Request) -> ReliabilityStore:
    return request.app.state.reliability_store


def get_experiment_store(request: Request) -> ExperimentStore:
    return request.app.state.experiment_store


def get_agent_manager(request: Request) -> AgentSessionManager:
    return request.app.state.agent_manager
