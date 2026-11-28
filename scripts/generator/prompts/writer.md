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

BEFORE YOU RETURN, CHECK THESE (an automatic checker rejects the draft if any fails; these were the most
common reasons earlier drafts were sent back)
1. STIMULUS LENGTH. Count the words in the stimulus "text" and "bullets" blocks only (tables, captions and the
   note do not count). The total must be between $min_words and $max_words words; aim for about $aim_words.
   Past-paper case-study text is often shorter than this, so add accurate context about the users, setting,
   materials or development process until you reach the minimum. Drafts of about 100-190 words have been
   rejected for 10-mark questions.
2. MARKING POINTS. Each part's answers list must have AT LEAST ONE MORE point than the part is worth:
   [1] needs 2 or more points, [2] needs 3 or more, [3] needs 4 or more, [4] needs 5 or more (for Evaluate,
   count the Strength, Limitation and Conclusion points). Count them for every part.
3. COMMAND TERM FIRST. The first word of each question must be exactly its command_term (or the question starts
   "Using Table 1, " followed by the command term). Only the allowed command terms may start a question: never
   start with "Calculate", "Compare", "Suggest", "Discuss", "Determine" or any other word. To ask for a
   calculation, put it inside an allowed term, e.g. "Using Table 1, outline the percentage saving ..." or
   "Using Table 1, analyse ... including a calculation of ...".
4. MARKS. Parts add up to exactly $marks, follow an allowed mark pattern, and no part is worth more than [4].

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
