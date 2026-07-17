"""Skill YAML config."""

from pydantic import BaseModel, Field


class SkillConfig(BaseModel):
    name: str = Field(description="Skill name, referenced from an agent's/team's `skills:` list.")
    description: str | None = Field(
        default=None, description="Short summary of what the skill does (SKILL.md frontmatter)."
    )
    content: str | None = Field(
        default=None,
        description=("SKILL.md-format body (YAML frontmatter + markdown instructions), parsed by StringSkills."),
    )
    github: str | None = Field(
        default=None,
        description=(
            "GitHub skill source: 'owner/repo[/sub/path][@ref]', e.g. "
            "'obra/superpowers/skills@main'. Repo is shallow-cloned (cached) and the "
            "path loaded via LocalSkills — a single skill folder or a dir of them."
        ),
    )
