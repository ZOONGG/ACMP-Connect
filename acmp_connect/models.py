"""Public structured MCP output contracts."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Result(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Example(Result):
    input: str
    output: str


class Problem(Result):
    id: int
    title: str
    url: str | None = None
    statement: str = ''
    limits: str | None = None
    sections: dict[str, str] = Field(default_factory=dict)
    examples: list[Example] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)


class TopicTask(Result):
    letter: str
    title: str = ''
    id: int
    course_url: str | None = None


class Candidate(Result):
    url: str
    title: str


class Topic(Result):
    url: str | None = None
    tasks: list[TopicTask]
    candidates: list[Candidate] = Field(default_factory=list)


class AccountStatus(Result):
    connected: bool
    connection_url: str
    acmp_user_id: int | None = None
    message: str | None = None


class Verdict(Result):
    id: int
    user: int
    task: int
    verdict: str
    state: Literal['pending', 'final', 'unknown']
    compiler: str | None = None
    test: str | None = None
    time: str | None = None
    memory: str | None = None
    url: str
    diagnostics: str | None = None
    compiler_log: str | None = None
    wait_timed_out: bool = False


class Upload(Result):
    operation_key: str
    state: Literal['reserved', 'uncertain', 'submitted', 'rejected']
    id: int | None
    task: int | None = None
    baseline_id: int | None = None
    compiler: str | None = None
    compiler_id: str | None = None
    message: str
    user: int | None = None
    verdict: str | None = None
    verdict_state: Literal['pending', 'final', 'unknown'] | None = None
    test: str | None = None
    time: str | None = None
    memory: str | None = None
    url: str | None = None
    diagnostics: str | None = None
    compiler_log: str | None = None
    wait_timed_out: bool | None = None


class History(Result):
    submissions: list[Verdict]


class Disconnection(Result):
    connected: bool
    data_deleted: bool
