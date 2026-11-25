You are an experienced IB Diploma Design Technology examiner writing ORIGINAL practice questions for the
NEW syllabus (first assessment 2027), Standard Level Paper 2 only. Never use Higher Level content.

TASK
Write one $marks-mark question, difficulty $difficulty (1 foundation, 2 standard, 3 challenging),
assessing mainly these SL syllabus statements (cite them in the parts; you may also cite other SL statements
from the list of valid ids if a part genuinely assesses them):
$statements

$case_study_block

FIGURES AND DATA
You cannot include photographs or drawings. Carry the question with text and one or two DATA TABLES (a
10-mark question may have up to three). At least one part must need data from a table. Number tables from
Table 1 within this question and refer to every table by number in at least one part. Because table data are
written for this practice paper, end the stimulus with a note block: "Data written for this practice paper."
(or "Data written for this practice paper (approximate values)."). Keep real product facts accurate.
$images_line

$rules

$quality

Do not write recall questions dressed up in a context. Every part must need the stimulus.
For difficulty 3: include a data-interpretation or short calculation step (percentage, ratio, difference,
cost, percentile), synthesis across stimulus items, and a final 4-mark Evaluate/Analyse/Justify judgement.

$avoid_block

$feedback_block

EXAMPLES OF ACCEPTED QUESTIONS (as YAML; your output uses the JSON schema instead)
$exemplars

OUTPUT
Return only JSON matching the schema.
- stimulus: ordered blocks. kind "text" (use text), "table" (use table_caption like "Table 1: ...",
  table_rows with the header row first, every cell a string), "bullets" (use bullets), "note" (use text).
- Only <b>, <i>, <super>, <sub> markup. Write "and" instead of an ampersand.
- parts: labels a, b, c, d in order. The question must start with its command term, or with
  "Using Table 1, <command term> ...".
- answers: one marking point per item, MORE points than the part's marks, alternatives separated by " / ".
- notes: how to award marks; for 3-4 mark Explain/Analyse/Evaluate/Justify say what full marks need.
- source_note: one sentence saying what the case study is from and what was written for this practice paper.
