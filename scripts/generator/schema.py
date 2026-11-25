"""The shapes Gemini must return (a "response schema"), written as Pydantic models.

Gemini's JSON mode is told to follow these models exactly, so the reply can be read by code instead of being
hand-written YAML. convert.py then turns a Draft into a question.yaml dictionary.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Block(BaseModel):
    kind: Literal["text", "table", "bullets", "note"]
    text: Optional[str] = Field(None, description="For kind text or note")
    table_caption: Optional[str] = Field(None, description="For kind table, e.g. 'Table 1: ...'")
    table_rows: Optional[list[list[str]]] = Field(None, description="For kind table: header row first")
    bullets: Optional[list[str]] = Field(None, description="For kind bullets")


class Part(BaseModel):
    label: str
    marks: int
    command_term: str
    syllabus: list[str]
    question: str
    answers: list[str]
    notes: str


class Draft(BaseModel):
    title: str
    marks: int
    difficulty: int
    source_note: str
    stimulus: list[Block]
    parts: list[Part]
    past_paper_images: Optional[str] = Field(
        None, description="Past-paper images that would improve this question, with page numbers, if any")


class Review(BaseModel):
    passed: bool = Field(description="True only if the draft could go to students after small wording edits")
    problems: list[str]
    fixes: list[str]


class Figure(BaseModel):
    caption: str
    page: int


class CaseStudy(BaseModel):
    reference: str = Field(description="IB reference such as 26M.2.SL.TZ1.6")
    product: str
    title: str = Field(description="Short title for the product or context")
    first_page: int
    last_page: int
    text: str = Field(description="The case-study (stimulus) text, complete, with all product facts and data")
    data: str = Field(description="Any tables or numerical data in the stimulus, written out as text")
    figures: list[Figure]
    original_questions: list[str] = Field(description="The original question parts, briefly")
    suits_topics: list[str] = Field(description="New-syllabus SL topic ids this case study could assess")


class CaseStudyIndexItem(BaseModel):
    reference: str
    product: str
    first_page: int
    last_page: int


class CaseStudyIndex(BaseModel):
    case_studies: list[CaseStudyIndexItem]
