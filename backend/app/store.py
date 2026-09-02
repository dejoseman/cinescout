"""In-memory project store.

CineScout keeps no user accounts and no personal data, so a process-local store
is the right amount of persistence for the product as scoped: a project lives as
long as the service instance that produced it. Swapping this for Firestore is a
single-class change, which is why every caller goes through this interface.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from typing import List, Optional

from .schemas import Project, ProjectStatus, ProjectSummary

#: Oldest projects are evicted beyond this to bound memory.
MAX_PROJECTS = 100


class ProjectStore:
    def __init__(self, max_projects: int = MAX_PROJECTS) -> None:
        self._projects: "OrderedDict[str, Project]" = OrderedDict()
        self._max = max_projects

    def create(self, project: Project) -> Project:
        self._projects[project.id] = project
        while len(self._projects) > self._max:
            self._projects.popitem(last=False)
        return project

    def get(self, project_id: str) -> Optional[Project]:
        return self._projects.get(project_id)

    def list(self) -> List[Project]:
        """Newest first."""
        return list(reversed(self._projects.values()))

    def summaries(self) -> List[ProjectSummary]:
        summaries = []
        for project in self.list():
            assessment = project.assessment
            summaries.append(
                ProjectSummary(
                    id=project.id,
                    title=project.brief.title,
                    city=project.brief.city,
                    country=project.brief.country,
                    status=project.status,
                    created_at=project.created_at,
                    readiness_score=assessment.readiness_score if assessment else None,
                    evidence_confidence=assessment.evidence_confidence if assessment else None,
                    critical_risks=assessment.critical_risks if assessment else 0,
                    open_actions=len(project.recommendations),
                    total_sources=len(project.sources),
                )
            )
        return summaries

    @property
    def running_count(self) -> int:
        return sum(
            1 for p in self._projects.values()
            if p.status in (ProjectStatus.RUNNING, ProjectStatus.QUEUED)
        )

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex[:12]


store = ProjectStore()
